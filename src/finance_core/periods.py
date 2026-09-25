"""
Split an upload into financial months (plan 4.3). Pure: no I/O, no config.

A financial month starts on the booking date of the first DUO or Anamata
salary income of a new cycle. A boundary on day ``split_day`` (15) or later
names the next calendar month, so DUO on 24-03-2026 opens 04/2026. Rows
before the first boundary in an upload are placed through the persisted
anchor: the last accepted boundary and the history of the ones before it.

The pipeline owns the anchor file (period_state.py) and passes the anchor in.
Rows arrive after ledger.filter_new, so every row seen here is new to the bot.

``force`` has one meaning: it suppresses the forceable checks (too many
fallback steps back, a label sequence that skips or repeats a month, a closed
period shorter than ``min_days``). It never changes how a row is labelled, and
it cannot label rows no rule covers.
"""

import math
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from finance_core.sheet_index import label_sort_key, next_label, parse_label, previous_label

__all__ = [
    "Anchor", "Period", "SplitResult", "SuspiciousSplitError",
    "split_into_periods", "advance_anchor", "label_for_boundary",
    "next_label", "previous_label", "label_sort_key",
    "parse_date", "format_date", "anchor_to_state", "anchor_from_state",
]

DATE_FORMAT = "%d-%m-%Y"          # csv_helper's booking_date, and the state file's


def parse_date(text: str) -> date:
    """'24-03-2026' -> date. Raises ValueError for anything else."""
    return datetime.strptime(text.strip(), DATE_FORMAT).date()


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def label_for_boundary(boundary: date, split_day: int) -> str:
    """Day ``split_day`` or later names the next month; earlier days their own."""
    label = f"{boundary.month:02d}/{boundary.year}"
    return next_label(label) if boundary.day >= split_day else label


@dataclass(frozen=True)
class Anchor:
    boundary: date                  # the last accepted boundary
    label: str                      # the label of the period it opened
    history: Tuple[Tuple[date, str], ...] = ()   # older (boundary, label), newest first

    def __post_init__(self):
        parse_label(self.label)
        history = tuple((b, lbl) for b, lbl in self.history)
        object.__setattr__(self, "history", history)
        newer = self.boundary
        for boundary, label in history:
            parse_label(label)
            if not boundary < newer:
                raise ValueError(f"anchor history must be strictly older and newest first: "
                                 f"{format_date(boundary)} after {format_date(newer)}")
            newer = boundary


@dataclass
class Period:
    label: str
    start: date                     # boundary date, or first row date for a leading remainder
    kind: Literal["leading", "closed", "open"]
    boundary_row: Optional[dict]
    transactions: List[dict]


@dataclass
class SplitResult:
    periods: List[Period]                        # chronological, one per label
    boundaries: List[Tuple[date, str]]           # accepted boundaries, in date order
    warnings: List[str] = field(default_factory=list)
    skipped_labels: List[str] = field(default_factory=list)   # months a forced split jumped


class SuspiciousSplitError(Exception):
    """The split looks wrong; nothing may be written."""

    def __init__(self, reason: str, boundaries: Sequence[Tuple[date, str]] = (), details: str = ""):
        self.reason = reason
        self.boundaries = list(boundaries)
        message = reason if not details else f"{reason}\n{details}"
        super().__init__(message)


@dataclass
class _Cluster:
    boundary: date
    label: str
    row: dict
    amount: float


# ── Candidates and clusters (rules 1 to 3) ──────────────────────────────────

def _amount(tx: dict) -> Optional[float]:
    try:
        return abs(float(tx["transaction_amount"]["amount"]))
    except (KeyError, TypeError, ValueError):
        return None


def _is_candidate(tx: dict, patterns, min_amount: float) -> bool:
    if tx.get("credit_debit_indicator") != "CRDT":
        return False
    amount = _amount(tx)
    if amount is None or amount < min_amount:
        return False
    texts = [(tx.get("creditor") or {}).get("name") or ""]
    texts += [t for t in tx.get("remittance_information") or [] if t]
    return any(p.search(text) for p in patterns for text in texts)


def _clusters(dated, anchor, patterns, min_amount, min_days, split_day) -> List[_Cluster]:
    clusters: List[_Cluster] = []
    for day, _, tx in dated:
        if not _is_candidate(tx, patterns, min_amount):
            continue
        # Rule 3: the anchor is itself a cluster boundary; candidates inside its
        # min_days window, or before it, are the anchor's boundary (or an older
        # one) seen again. Filtering before clustering keeps a spurious early
        # candidate from absorbing the real next boundary.
        if anchor is not None and (day - anchor.boundary).days < min_days:
            continue
        # Rule 2: measured from the cluster's boundary, never from the previous
        # candidate, so clusters cannot chain.
        if clusters and (day - clusters[-1].boundary).days < min_days:
            continue
        clusters.append(_Cluster(day, label_for_boundary(day, split_day), tx, _amount(tx)))
    return clusters


# ── Rule 7 ──────────────────────────────────────────────────────────────────

def _check_split(boundaries: Sequence[Tuple[date, str]], anchor: Optional[Anchor],
                 min_days: int) -> Tuple[List[str], List[str]]:
    """
    Contiguity and length over the accepted boundaries, starting from the
    anchor when there is one. Returns (problems, skipped labels).
    """
    problems: List[str] = []
    skipped: List[str] = []
    chain = ([(anchor.boundary, anchor.label)] if anchor else []) + list(boundaries)
    for (prev_day, prev_label), (day, label) in zip(chain, chain[1:]):
        expected = next_label(prev_label)
        if label != expected:
            problems.append(f"{label} opened on {format_date(day)} does not follow {prev_label}")
            walk = expected
            while label_sort_key(walk) < label_sort_key(label):
                skipped.append(walk)
                walk = next_label(walk)
        length = (day - prev_day).days
        if length < min_days:
            problems.append(f"{prev_label} from {format_date(prev_day)} to {format_date(day)} "
                            f"is only {length} days, under {min_days}")
    return problems, skipped


# ── Leading rows (rules 4 and 5) ────────────────────────────────────────────

def _step_back(label: str, steps: int) -> str:
    for _ in range(steps):
        label = previous_label(label)
    return label


def _describe(clusters: Sequence[_Cluster]) -> str:
    if not clusters:
        return "No boundary was detected in this upload."
    lines = ["Detected boundaries:"]
    for c in clusters:
        lines.append(f"  {format_date(c.boundary)}  {_bucket(c.amount)}  {c.label}")
    return "\n".join(lines)


def _bucket(amount: Optional[float]) -> str:
    if amount is None:
        return "amount unknown"
    if amount < 1000:
        return "under 1000"
    low = int(amount // 1000) * 1000
    return f"{low}-{low + 999}"


# ── The splitter ────────────────────────────────────────────────────────────

def split_into_periods(transactions, *, anchor: Optional[Anchor], markers, min_amount: float,
                       min_days: int, max_days: int, step_days: int, split_day: int,
                       force: bool = False) -> SplitResult:
    """
    Label every transaction with its financial month and group them.

    Returns a SplitResult whose periods hold copies of the input rows, each
    with ``period_label`` set; the input is not modified. Raises
    SuspiciousSplitError, and nothing may be written, when the split looks
    wrong (rules 4, 5 and 7), and ValueError for an unparsable booking date.
    """
    dated = sorted(((parse_date(t["booking_date"]), i, t) for i, t in enumerate(transactions)),
                   key=lambda item: (item[0], item[1]))
    if not dated:
        return SplitResult([], [])

    patterns = [re.compile(m) for m in markers]
    clusters = _clusters(dated, anchor, patterns, min_amount, min_days, split_day)
    boundaries = [(c.boundary, c.label) for c in clusters]
    details = _describe(clusters)
    warnings: List[str] = []

    def abort(reason):
        raise SuspiciousSplitError(reason, boundaries, details)

    first_boundary = clusters[0].boundary if clusters else None
    leading = [(day, i) for day, i, _ in dated if first_boundary is None or day < first_boundary]

    # Rule 5 first: rows no rule can label abort whatever ``force`` says.
    if anchor is not None and first_boundary is None:
        beyond = [day for day, _ in leading if (day - anchor.boundary).days >= max_days]
        if beyond:
            abort(f"rows from {format_date(beyond[0])} are {max_days} or more days after the last "
                  f"boundary ({format_date(anchor.boundary)}, {anchor.label}) and the upload holds "
                  f"no new one: re-export from {format_date(anchor.boundary)} so the DUO row is "
                  f"included, or set the anchor with scripts/seed_state.py --set-anchor")
    if anchor is None and leading:
        # Without an anchor the reference is the first boundary, or failing
        # that the earliest row; a span of max_days or more means a boundary
        # happened that the upload does not show.
        if first_boundary is not None:
            too_old = [day for day, _ in leading if (first_boundary - day).days >= max_days]
        else:
            too_old = [day for day, _ in leading if (day - leading[0][0]).days >= max_days]
        if too_old:
            abort(f"no period anchor yet, and the rows around {format_date(too_old[0])} are "
                  f"{max_days} or more days from any boundary in the upload: seed the anchor with "
                  f"scripts/seed_state.py first")

    # Rule 4: label the leading rows.
    leading_labels: Dict[int, str] = {}
    too_far: List[date] = []
    if anchor is not None:
        chain = ((anchor.boundary, anchor.label),) + anchor.history
        oldest_day, oldest_label = chain[-1]
        for day, i in leading:
            if day >= anchor.boundary:
                label = anchor.label
            else:
                label = next((lbl for b, lbl in chain[1:] if day >= b), None)
                if label is None:
                    steps = math.ceil((oldest_day - day).days / step_days)
                    if steps > 1:
                        too_far.append(day)
                    label = _step_back(oldest_label, steps)
            leading_labels[i] = label
    elif leading:
        if clusters:
            label = previous_label(clusters[0].label)
            warnings.append(f"no period anchor: rows before {format_date(first_boundary)} were "
                            f"put in {label}, the month before the first boundary")
        else:
            label = label_for_boundary(leading[0][0], split_day)
            warnings.append(f"no period anchor and no boundary in the upload: every row was put "
                            f"in {label}, from the earliest row date {format_date(leading[0][0])}")
        leading_labels = {i: label for _, i in leading}

    problems: List[str] = []
    if too_far:
        problems.append(f"rows from {format_date(too_far[0])} are more than one "
                        f"{step_days}-day step older than the oldest known boundary "
                        f"({format_date(chain[-1][0])})")
    contiguity, skipped = _check_split(boundaries, anchor, min_days)
    problems += contiguity
    if problems and not force:
        abort("; ".join(problems))
    if problems:
        warnings += [f"forced: {p}" for p in problems]
        warnings += [f"{label} skipped: the upload has no boundary for it" for label in skipped]

    # Group rows into periods (rules 6, 8, 9).
    starts = [c.boundary for c in clusters]
    by_label: Dict[str, Period] = {}
    for day, idx, tx in dated:
        if first_boundary is not None and day >= first_boundary:
            i = bisect_right(starts, day) - 1         # same-day rows join the new period
            c = clusters[i]
            label, kind, start, row = c.label, ("open" if i == len(clusters) - 1 else "closed"), c.boundary, c.row
        else:
            label, kind, start, row = leading_labels[idx], "leading", day, None
        period = by_label.get(label)
        if period is None:
            # A label can recur only in a forced split (e.g. a bonus that
            # repeats a month); its rows share the one sheet, so they merge.
            period = by_label[label] = Period(label, start, kind, row, [])
        elif period.boundary_row is None and row is not None:
            period.boundary_row = row
        period.transactions.append({**tx, "period_label": label})

    periods = sorted(by_label.values(), key=lambda p: label_sort_key(p.label))
    return SplitResult(periods, boundaries, warnings, skipped)


# ── Anchor lifecycle ────────────────────────────────────────────────────────

def advance_anchor(anchor: Optional[Anchor], result: SplitResult) -> Optional[Anchor]:
    """
    The anchor after a split has passed its checks: the last accepted
    boundary, with every superseded one -- the old anchor and each earlier
    boundary of this upload -- pushed onto history, so the real intervals
    accumulate as the bot runs.
    """
    newer = [(b, lbl) for b, lbl in result.boundaries if anchor is None or b > anchor.boundary]
    if not newer:
        return anchor
    history = tuple(reversed(newer[:-1]))
    if anchor is not None:
        history += ((anchor.boundary, anchor.label),) + anchor.history
    boundary, label = newer[-1]
    return Anchor(boundary, label, history)


def anchor_to_state(anchor: Optional[Anchor]) -> Optional[dict]:
    """The JSON form of data/period_state.json; None means no anchor (no file)."""
    if anchor is None:
        return None
    return {
        "anchor": {"boundary": format_date(anchor.boundary), "label": anchor.label},
        "history": [[format_date(b), lbl] for b, lbl in anchor.history],
    }


def anchor_from_state(state: Optional[dict]) -> Optional[Anchor]:
    """Inverse of anchor_to_state. Raises ValueError on a malformed state."""
    if state is None or state.get("anchor") is None:
        return None
    try:
        head = state["anchor"]
        history = tuple((parse_date(b), lbl) for b, lbl in state.get("history") or ())
        return Anchor(parse_date(head["boundary"]), head["label"], history)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed period state: {exc}") from exc
