#!/usr/bin/env python3
"""
Score the categoriser against hand-checked months (plan section 6, evaluation).

Runs old ASN exports through the real CategorizationEngine, one financial
month per call as production does, and compares each row's category with the
category the user gave that row in the 2024/2025 sheets. Prints scores only:
counts, percentages and category names. It never prints a date, amount,
description, counterparty or remittance text, and it never shows a log
message (the categoriser's logs are counted, not printed, and bucketed by
fixed labels such as `exit 1, subtype=error_max_turns`). A crash prints the
exception type and place only; --debug shows the full traceback and may show
row content.

What goes to the AI is exactly what production sends: the anonymised batch
prompt. Nothing is written anywhere: no ledger, no run state, no sheet.

On the Pi, inside the bot's container, with this branch's code (the running
image's config and service account are used as they are):

    # on the workstation
    git archive --format=tar HEAD src/automation src/finance_core src/constants.py \\
        | ssh rp5 'mkdir -p /tmp/eval && cat > /tmp/eval/branch-src.tar'
    scp scripts/eval_categoriser.py rp5:/tmp/eval/
    scp <your 2024 and 2025 ASN exports>.csv rp5:/tmp/eval/
    # on the Pi
    docker cp /tmp/eval finance-automation-bot:/tmp/
    docker exec finance-automation-bot sh -c 'cd /tmp/eval && tar -xf branch-src.tar'
    docker exec finance-automation-bot python /tmp/eval/eval_categoriser.py \\
        --src /tmp/eval/src --dry-run /tmp/eval/*.csv
    # when the dry run matches well (add --map OLD=NEW for renamed categories):
    docker exec finance-automation-bot python /tmp/eval/eval_categoriser.py \\
        --src /tmp/eval/src --model sonnet --runs 2 /tmp/eval/*.csv
    # where more regex rules would help: regex only, no AI, a few minutes.
    # The names file is for the user's eyes; the printed report is not.
    docker exec finance-automation-bot python /tmp/eval/eval_categoriser.py \\
        --src /tmp/eval/src --rules --names-out /tmp/eval/rule-names.tsv \\
        --draft-out /tmp/eval/rule-draft.txt /tmp/eval/*.csv
    # (rule_coverage.py must sit next to this script: scp it along.)
    # With the household's own rules and account roles, as the bot would run
    # them (both files private, 0600, readable by the container's user); add
    # --amount-cuts N07=100,125,150 on a run WITHOUT --local-rules, so the
    # group ids are the draft's:
    docker exec finance-automation-bot python /tmp/eval/eval_categoriser.py \\
        --src /tmp/eval/src --rules --local-rules /tmp/eval/local_rules.tsv \\
        --account-roles /tmp/eval/account_roles.txt /tmp/eval/*.csv
    # Shadow-eval (jev-investigation.md §5.1 step 1; scripts/shadow_eval.py
    # must sit next to this script: scp it along). Sonnet on every month, with
    # the household's rules, writing the rows file and its answers (0600, no
    # transaction text in either):
    docker exec finance-automation-bot python /tmp/eval/eval_categoriser.py \\
        --src /tmp/eval/src --model sonnet --local-rules /tmp/eval/local_rules.tsv \\
        --account-roles /tmp/eval/account_roles.txt \\
        --rows-out /tmp/eval/rows.jsonl --predictions-out /tmp/eval/pred-sonnet.jsonl \\
        /tmp/eval/*.csv
    # The local arms' training export, owner-run: rules only, no AI, every
    # scored row WITH its text. Copy it straight to the workstation (0600)
    # and delete it from the Pi; it is never printed and never pushed.
    docker exec finance-automation-bot python /tmp/eval/eval_categoriser.py \\
        --src /tmp/eval/src --local-rules /tmp/eval/local_rules.tsv \\
        --account-roles /tmp/eval/account_roles.txt \\
        --export-out /tmp/eval/export.jsonl /tmp/eval/*.csv
    # Hosted Jev (arm 2; jev_client.py next to this script too): rules only,
    # then one zero-data-retention decision per routed row on the anonymised
    # text. The key file is placed with token-place and never printed.
    docker exec finance-automation-bot python /tmp/eval/eval_categoriser.py \\
        --src /tmp/eval/src --local-rules /tmp/eval/local_rules.tsv \\
        --account-roles /tmp/eval/account_roles.txt \\
        --openrouter-key-file /tmp/eval/openrouter.key \\
        --jev-out /tmp/eval/pred-jev.jsonl /tmp/eval/*.csv
    # afterwards, remove the exports from both places
    docker exec finance-automation-bot rm -rf /tmp/eval
    rm -rf /tmp/eval

The glob is expanded by the Pi's shell against the Pi's /tmp/eval, which
holds the same files as the container's.
"""

import argparse
import asyncio
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for candidate in (os.path.join(PROJECT_ROOT, "src"), "/app/src"):
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

UNDECIDED = {"! Nog in te delen !", "CACHED"}
NAME_MAX = 40            # longest category name the report prints
SHOW_MIN = 2             # an unmapped name must occur this often to be shown
THRESHOLDS = (0.9, 0.6, 0.0)
MIN_INTERVAL = 1.2        # seconds between Sheets calls: under 50 a minute
RETRY_DELAYS = (20, 40, 80)
SHEET_NAME = re.compile(r"^Maandelijks Budget (\d{2})/(\d{4})$")
DMY = re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── logging and crashes: counted, never printed ─────────────────────────────

# Fixed phrases a record may contain, and the label printed for each. A
# record is described by these labels only; its text is never printed.
FAILURE_PHRASES = (
    ("stdout not json", "stdout not JSON"),
    ("no output", "no output"),
    ("timed out", "timed out"),
    ("overloaded", "overloaded"),
    ("rate limit", "rate limit"),
    ("usage limit", "usage limit"),
    ("prompt is too long", "prompt too long"),
    ("credit balance", "credit balance"),
    ("unknown error", "unknown error"),
    ("retrying once", "retry"),
    ("budget spent", "budget spent"),
    ("missing ids", "missing ids"),
    ("parse fail", "parse failure"),
)
EXIT_CODE = re.compile(r"\bexit (-?\d{1,3})\b")
# CLI enum values only: lower-case snake_case, so no name can pass.
CLI_FIELD = re.compile(r"\b(subtype|terminal_reason)=([a-z_]{1,40})(?![\w])")
API_STATUS = re.compile(r"\bapi error: (\d{3})\b", re.I)


def failure_labels(record) -> str:
    """Describe a log record by exception class and fixed labels only."""
    msg = record.getMessage()
    labels = []
    if record.exc_info and record.exc_info[0]:
        labels.append(record.exc_info[0].__name__)
    labels += [f"exit {m}" for m in EXIT_CODE.findall(msg)[:1]]
    labels += [f"{k}={v}" for k, v in CLI_FIELD.findall(msg)]
    labels += [f"API {m}" for m in API_STATUS.findall(msg)[:1]]
    low = msg.lower()
    labels += [label for phrase, label in FAILURE_PHRASES if phrase in low]
    return ", ".join(labels) or "other"


class LogCounter:
    """A root handler that counts records and drops their messages."""

    def __init__(self):
        import logging
        self.counts = Counter()
        self.kinds = Counter()

        class Handler(logging.Handler):
            def emit(handler, record):
                self.counts[(record.name, record.levelname)] += 1
                self.kinds[(record.name, record.levelname,
                            failure_labels(record))] += 1

        self.handler = Handler(level=logging.WARNING)

    def summary(self):
        warnings = sum(n for (_, lvl), n in self.counts.items() if lvl == "WARNING")
        errors = sum(n for (_, lvl), n in self.counts.items() if lvl in ("ERROR", "CRITICAL"))
        lines = [f"log: {warnings} warning(s), {errors} error(s) (messages withheld)"]
        for (name, lvl), n in sorted(self.counts.items()):
            lines.append(f"  {name} {lvl}: {n}")
        if self.kinds:
            lines.append("log kinds (fixed labels only):")
        for (name, lvl, kind), n in sorted(self.kinds.items()):
            lines.append(f"  {name} {lvl} [{kind}]: {n}")
        return lines


def install_quiet_logging() -> LogCounter:
    import logging
    counter = LogCounter()
    root = logging.getLogger()
    root.handlers[:] = [counter.handler]
    root.setLevel(logging.WARNING)
    return counter


class InputError(Exception):
    """A file or argument the run cannot use. The message is written here,
    never taken from row content, so it is printed."""


def guarded(fn, debug=False):
    try:
        result = fn()
        return 0 if result is None else result
    except InputError as exc:
        print(f"stopped: {exc}")
        return 2
    except Exception as exc:                     # noqa: BLE001 - the point
        if debug:
            raise
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        status = getattr(getattr(exc, "response", None), "status_code", None)
        http = f" (HTTP {status})" if isinstance(status, int) else ""
        print(f"stopped: {type(exc).__name__}{http} at {os.path.basename(frame.filename)}:{frame.lineno}"
              " (message withheld; --debug shows it and may show row content)")
        return 2


# ── the sheets ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SheetRow:
    label: str
    block: str           # "expenses" or "income"
    date: str            # ISO
    amount: str          # absolute, 2 decimals
    category: str
    switched: bool       # negative amount: moved to the other block by hand


def _is_date(v) -> bool:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return 20000 < v < 80000                 # a Sheets date serial
    s = str(v).strip()
    return bool(DMY.match(s) or ISO.match(s))


def detect_start_row(values):
    """1-based number of the first row whose first cell is a date, or None."""
    for i, row in enumerate(values, start=1):
        if row and _is_date(row[0]):
            return i
    return None


def block_rows(label, block, values, start_row):
    from finance_core.row_tuple import canonical_amount, canonical_date
    rows = []
    for row in values[start_row - 1:]:
        row = list(row) + [""] * (4 - len(row))
        if str(row[0]).strip() == "":
            continue
        try:
            x = float(row[1])
            switched, amount = x < 0, canonical_amount(abs(x))
        except (TypeError, ValueError):
            switched, amount = False, canonical_amount(row[1])
        rows.append(SheetRow(label, block, canonical_date(row[0]), amount,
                             str(row[3]).strip(), switched))
    return rows


def select_sheets(files, years, only):
    """(label, id) for every sheet named for a month of `years`, chronological."""
    picked, ignored = [], 0
    for f in files:
        m = SHEET_NAME.match(f["name"].strip())
        if not m or m.group(2) not in years:
            ignored += 1
            continue
        label = f"{m.group(1)}/{m.group(2)}"
        if only and label not in only:
            continue
        picked.append((label, f["id"]))
    picked.sort(key=lambda p: (p[0][3:], p[0][:2]))
    return picked, ignored


def read_sheets(gc, picked, tab, say, sleep=time.sleep, clock=time.monotonic):
    """Every sheet's rows, in two requests per sheet (open, one batchGet).

    Sheets allows 60 reads a minute and a refused request still counts, so
    calls are spaced MIN_INTERVAL apart and a 429 or 5xx waits RETRY_DELAYS.
    """
    from finance_core.google_retry import status_of, with_retry
    last = [None]

    def call(fn, what):
        def paced():
            if last[0] is not None:
                wait = MIN_INTERVAL - (clock() - last[0])
                if wait > 0:
                    sleep(wait)
            last[0] = clock()
            return fn()
        return with_retry(paced, delays=RETRY_DELAYS, sleep=sleep, what=what)

    ranges = [f"'{tab}'!B1:E", f"'{tab}'!G1:J"]
    rows = []
    for label, sheet_id in picked:
        sh = call(lambda: gc.open_by_key(sheet_id), f"open {label}")
        try:
            got = call(lambda: sh.values_batch_get(
                ranges, params={"valueRenderOption": "UNFORMATTED_VALUE"}), f"read {label}")
        except Exception as exc:
            if status_of(exc) != 400:            # 400: the range names no such tab
                raise
            tabs = [w.title for w in call(sh.worksheets, f"tabs {label}")]
            say(f"  {label}: no {tab!r} tab (tabs: {tabs}); skipped")
            continue
        value_ranges = got.get("valueRanges", [])
        parts = []
        for i, block in enumerate(("expenses", "income")):
            values = value_ranges[i].get("values", []) if i < len(value_ranges) else []
            start = detect_start_row(values)
            block_got = block_rows(label, block, values, start) if start else []
            rows.extend(block_got)
            parts.append(f"{block} from row {start} ({len(block_got)} rows)" if start
                         else f"{block} empty")
        say(f"  {label}: " + ", ".join(parts))
    return rows


# ── matching export rows to sheet rows ──────────────────────────────────────

@dataclass
class Record:
    index: int
    tx: object
    label: str
    group: tuple         # (label, date, amount, block): rows sharing a key


@dataclass
class Match:
    records: list = field(default_factory=list)
    truths: dict = field(default_factory=lambda: defaultdict(list))
    counts: Counter = field(default_factory=Counter)
    unmapped: Counter = field(default_factory=Counter)
    per_label: Counter = field(default_factory=Counter)


def truth_for(raw_category, block, valid, mapping):
    """(category, reason): reason is ok, undecided, blank or unmapped."""
    name = mapping.get(raw_category, raw_category)
    if not raw_category:
        return None, "blank"
    if raw_category in UNDECIDED or name in UNDECIDED:
        return None, "undecided"
    if name in valid[block]:
        return name, "ok"
    return None, "unmapped"


def match_rows(txs, sheet_rows, valid, mapping):
    from finance_core.row_tuple import block_for, canonical_amount, canonical_date
    pool = defaultdict(list)
    for row in sheet_rows:
        pool[(row.date, row.amount, row.block)].append(row)
    other = {"expenses": "income", "income": "expenses"}
    m = Match()
    m.counts["export_rows"] = len(txs)
    for tx in txs:
        try:
            amount = canonical_amount(abs(float(tx["transaction_amount"]["amount"])))
        except (KeyError, TypeError, ValueError):
            m.counts["unmatched"] += 1
            continue
        date = canonical_date(tx.get("booking_date", ""))
        block = block_for(tx).name
        if pool[(date, amount, block)]:
            row = pool[(date, amount, block)].pop()
        elif pool[(date, amount, other[block])]:
            pool[(date, amount, other[block])].pop()
            m.counts["other_block"] += 1
            continue
        else:
            m.counts["unmatched"] += 1
            continue
        truth, reason = truth_for(row.category, block, valid, mapping)
        if reason != "ok":
            m.counts[reason] += 1
            if reason == "unmapped":
                m.unmapped[row.category] += 1
            continue
        group = (row.label, date, amount, block)
        m.records.append(Record(len(m.records), tx, row.label, group))
        m.truths[group].append(truth)
        m.per_label[row.label] += 1
    m.counts["scored"] = len(m.records)
    m.counts["sheet_rows_unmatched"] = sum(len(v) for v in pool.values())
    return m


# ── categorising and scoring ────────────────────────────────────────────────

def _label_key(label):
    return (label[3:], label[:2])


async def categorise(engine, records, parallel, say):
    """One batch_categorize call per month, as production calls it per period."""
    by_label = defaultdict(list)
    for r in records:
        by_label[r.label].append(r)
    results = [None] * len(records)
    kwargs = {} if parallel is None else {"max_parallel": parallel}
    labels = sorted(by_label, key=_label_key)
    for n, label in enumerate(labels, 1):
        started = time.monotonic()
        group = by_label[label]
        out = await engine.batch_categorize([r.tx for r in group], **kwargs)
        for r, res in zip(group, out):
            results[r.index] = res
        say(f"  {label}: {len(group)} rows in {time.monotonic() - started:.0f} s ({n}/{len(labels)})")
    return results


def score(records, truths, results):
    """Per record: truth, prediction, method, confidence, correct.

    Rows sharing a key (same month, date, amount and block) are scored as a
    multiset: a prediction is correct when it equals one of the group's
    categories not yet claimed, so the arbitrary pairing inside the group
    never costs a point.
    """
    by_group = defaultdict(list)
    for r in records:
        by_group[r.group].append(r)
    out = [None] * len(records)
    for group, members in by_group.items():
        remaining = Counter(truths[group])
        wrong = []
        for r in members:
            res = results[r.index]
            pred = getattr(res, "category", None)
            if pred is not None and remaining[pred] > 0:
                remaining[pred] -= 1
                out[r.index] = dict(truth=pred, pred=pred, correct=True)
            else:
                wrong.append((r, pred))
        leftovers = list(remaining.elements())
        for (r, pred), truth in zip(wrong, leftovers):
            out[r.index] = dict(truth=truth, pred=pred, correct=False)
        for r in members:
            res = results[r.index]
            out[r.index].update(method=getattr(res, "method", "none"),
                                confidence=float(getattr(res, "confidence", 0.0) or 0.0))
    return out


def _band(confidence):
    return "high" if confidence >= 0.85 else "medium" if confidence >= 0.5 else "low"


def _is_ai_answer(row):
    return row["method"] in ("ai_auto", "ai_manual_needed") and row["pred"] is not None


def build_report(rows):
    def tally(selected):
        selected = list(selected)
        return (len(selected), sum(1 for r in selected if r["correct"]))

    ai = [r for r in rows if _is_ai_answer(r)]
    non_regex = [r for r in rows if r["method"] != "regex"]
    thresholds = []
    for t in THRESHOLDS:
        written = [r for r in non_regex if _is_ai_answer(r) and r["confidence"] >= t]
        ok = sum(1 for r in written if r["correct"])
        flagged = len(non_regex) - len(written)
        thresholds.append(dict(threshold=t, flagged=flagged, written=len(written),
                               written_ok=ok, attention=flagged + len(written) - ok,
                               total=len(non_regex)))
    categories = defaultdict(list)
    for r in rows:
        categories[r["truth"]].append(r)
    confusions = Counter((r["truth"], r["pred"]) for r in rows if not r["correct"])
    return {
        "overall": tally(rows),
        "methods": {
            "regex": tally(r for r in rows if r["method"] == "regex"),
            "ai": tally(ai),
            "no answer": tally(r for r in rows
                               if r["method"] != "regex" and not _is_ai_answer(r)),
        },
        "bands": {b: tally(r for r in ai if _band(r["confidence"]) == b)
                  for b in ("high", "medium", "low")},
        "thresholds": thresholds,
        "categories": {c: tally(rs) for c, rs in categories.items()},
        "confusions": sorted(confusions.items(),
                             key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or "")),
    }


def disagreement(preds_per_run):
    """(rows, rows whose prediction differs between any two runs)."""
    n = len(preds_per_run[0])
    differ = sum(1 for i in range(n) if len({run[i] for run in preds_per_run}) > 1)
    return n, differ


# ── the report ──────────────────────────────────────────────────────────────

def _name(s):
    s = "(no answer)" if s is None else str(s)
    return s if len(s) <= NAME_MAX else s[:NAME_MAX] + "..."


def _pct(n, ok):
    return f"{ok}/{n} = {100 * ok / n:.1f}%" if n else "0/0"


def format_unmapped(unmapped):
    shown = {k: v for k, v in unmapped.items() if v >= SHOW_MIN}
    hidden = {k: v for k, v in unmapped.items() if v < SHOW_MIN}
    lines = []
    if shown:
        lines.append("sheet categories with no match today (add --map OLD=NEW):")
        for name, n in sorted(shown.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {_name(name)!r}: {n} row(s)")
    if hidden:
        lines.append(f"  {sum(hidden.values())} row(s) under {len(hidden)} name(s) "
                     "used only once are not shown")
    return lines


def format_matching(m):
    c = m.counts
    lines = [
        f"export rows: {c['export_rows']}, collapsed as duplicates across exports: {c['collapsed']}",
        f"scored: {c['scored']}; not scored: {c['unmatched']} not found in a sheet, "
        f"{c['other_block']} found in the other block (switched by hand), "
        f"{c['undecided']} left undecided in the sheet, {c['blank']} with a blank category, "
        f"{c['unmapped']} with an unmapped category",
        f"sheet rows no export row matched: {c['sheet_rows_unmatched']}",
    ]
    ambiguous = sum(1 for t in m.truths.values() if len(t) > 1 and len(set(t)) > 1)
    lines.append(f"key groups with several rows of different categories: {ambiguous}")
    lines.append("scored rows per month: " + ", ".join(
        f"{label} {n}" for label, n in sorted(m.per_label.items(), key=lambda kv: _label_key(kv[0]))))
    return lines + format_unmapped(m.unmapped)


def format_report(rep, m, runs=None, brief=False):
    lines = [f"overall: {_pct(*rep['overall'])}"]
    for k in ("regex", "ai", "no answer"):
        lines.append(f"  {k}: {_pct(*rep['methods'][k])}")
    lines.append("AI answers by confidence band (high 0.9, medium 0.6, low 0.3):")
    for b in ("high", "medium", "low"):
        lines.append(f"  {b}: {_pct(*rep['bands'][b])}")
    lines.append("threshold (rows below it are written flagged; 0.75 today acts as 0.9):")
    for t in rep["thresholds"]:
        share = 100 * t["flagged"] / t["total"] if t["total"] else 0.0
        lines.append(f"  >= {t['threshold']:.1f}: flagged {t['flagged']}/{t['total']} ({share:.1f}%), "
                     f"written unflagged {_pct(t['written'], t['written_ok'])} correct, "
                     f"rows needing you: {t['attention']}")
    if not brief:
        lines.append("per true category:")
        for cat, (n, ok) in sorted(rep["categories"].items(), key=lambda kv: -kv[1][0]):
            lines.append(f"  {_name(cat)}: {_pct(n, ok)}")
        lines.append("most common mistakes (true -> predicted):")
        for (truth, pred), n in rep["confusions"][:10]:
            lines.append(f"  {_name(truth)} -> {_name(pred)}: {n}")
    if runs and len(runs) > 1:
        n, differ = disagreement([[r["pred"] for r in run] for run in runs])
        lines.append(f"runs disagree on {differ}/{n} rows ({100 * differ / n:.1f}%)" if n else "")
    return lines


# ── main ────────────────────────────────────────────────────────────────────

def parse_pair(arg):
    key, sep, value = arg.partition("=")
    if not sep or not key.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"expected OLD=NEW or LABEL=ID, got {arg!r}")
    return key.strip(), value.strip()


def parse_month(arg):
    if not re.fullmatch(r"(0[1-9]|1[0-2])/\d{4}", arg):
        raise argparse.ArgumentTypeError(f"expected a sheet month MM/YYYY, got {arg!r}")
    return arg


GROUP_ARG = re.compile(r"^[A-Z]\d{1,4}$")
IBAN_SHAPE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$")


def parse_cuts(arg):
    """`N07=100,125,150` -> ("N07", [100.0, 125.0, 150.0])."""
    gid, _, amounts = arg.partition("=")
    try:
        values = [float(a) for a in amounts.split(",")]
    except ValueError:
        values = None
    if not GROUP_ARG.match(gid) or not values or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("expected a group id and amounts, e.g. N07=100,125,150")
    return gid, values


def load_account_roles(path):
    """{role: [iban, ...]} from a private file: one account per line, the role
    first (savings, partner_personal, user_personal), then the IBAN, spaces
    allowed. Errors name the line, never its text."""
    from finance_core.tx_features import ROLES, normalise_iban
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        raise InputError("the account roles file does not exist") from None
    roles, seen = {}, set()
    for n, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        role, _, rest = line.strip().partition(" ")
        if role not in ROLES:
            raise InputError(f"account roles line {n}: not a known role ({', '.join(ROLES)})")
        iban = normalise_iban(rest)
        if not IBAN_SHAPE.match(iban):
            raise InputError(f"account roles line {n}: no IBAN after the role")
        if iban in seen:
            raise InputError(f"account roles line {n}: an account given twice")
        seen.add(iban)
        roles.setdefault(role, []).append(iban)
    return roles


def load_rules_file(path):
    from finance_core.local_rules import LocalRulesError, load_local_rules
    if not os.path.exists(path):
        raise InputError("the local rules file does not exist")
    try:
        return load_local_rules(path)
    except LocalRulesError as exc:          # names the line and the problem only
        raise InputError(str(exc)) from None


def build_engine(model, local_rules, make_ai=None):
    """The engine as production builds it, with the eval's local rules."""
    from finance_core.categorization_engine import CategorizationEngine
    if make_ai is None:
        from automation.ai_categorizer import ClaudeCategorizer
        make_ai = lambda m: ClaudeCategorizer(model=m)          # noqa: E731
    return CategorizationEngine(ai_categorizer=make_ai(model), ai_enabled=True,
                                local_rules=local_rules)


def rules_engine(local_rules):
    """The engine with the AI off: only the rules decide, the rest comes back
    with method 'none'. Tells which rows today's rules send to the AI."""
    from finance_core.categorization_engine import CategorizationEngine
    return CategorizationEngine(ai_categorizer=None, ai_enabled=False, local_rules=local_rules)


# ── shadow-eval files (jev-investigation.md §5.1 step 1; scripts/shadow_eval.py) ──

def _is_routed(result) -> bool:
    """A row today's rules do not decide, so production sends it to the AI."""
    return getattr(result, "method", "none") != "regex"


def rows_payload(m, results):
    """(fingerprint, rows) for the rows file: per scored row its month, block,
    key group, true category and routing. No transaction content."""
    from shadow_eval import fingerprint
    group_ids, taken, rows = {}, Counter(), []
    for r in m.records:
        gid = group_ids.setdefault(r.group, len(group_ids))
        truth = m.truths[r.group][taken[r.group]]
        taken[r.group] += 1
        rows.append({"id": r.index, "label": r.label, "block": r.group[3], "group": gid,
                     "truth": truth, "routed": _is_routed(results[r.index])})
    return fingerprint(r.group for r in m.records), rows


def predictions_payload(m, results):
    """One line per routed row: the answer and its confidence (None: no answer)."""
    out = []
    for r in m.records:
        res = results[r.index]
        if not _is_routed(res):
            continue
        out.append({"id": r.index, "category": getattr(res, "category", None),
                    "confidence": float(getattr(res, "confidence", 0.0) or 0.0)})
    return out


def _counterparty(tx):
    for side in ("creditor", "debtor"):
        name = ((tx.get(side) or {}).get("name") or "").strip()
        if name:
            return name
    return ""


def export_payload(m, results, roles=None):
    """(fingerprint, rows) for the private export: the rows file's fields plus
    the row's own text and features, for the local arms. Never printed."""
    from finance_core import tx_features as tf
    from finance_core.pot_links import pot_hints
    if roles is not None:
        tf.use_account_roles(roles)
    savings = set(tf.account_roles().get("savings", []))
    hinted = set()
    by_label = defaultdict(list)
    for r in m.records:
        by_label[r.label].append(r)
    for recs in by_label.values():
        txs = [r.tx for r in recs]
        routed = [i for i, r in enumerate(recs) if _is_routed(results[r.index])]
        hints = pot_hints(txs, routed, savings) if savings else {}
        hinted.update(recs[i].index for i in hints)
    fp, rows = rows_payload(m, results)
    for row, r in zip(rows, m.records):
        tx, day = r.tx, tf.tx_day(r.tx)
        row["tx"] = {
            "direction": tf.tx_direction(tx), "amount": tf.tx_amount(tx), "code": tf.tx_code(tx),
            "weekday": None if day is None else day.weekday(), "hour": tf.tx_hour(tx),
            "counterparty": _counterparty(tx), "remittance": tf.remittance_text(tx),
            "counterparty_iban": tf.normalise_iban(tx.get("counterparty_iban")),
            "account_role": tf.account_role(tx), "pot_hint": r.index in hinted}
    return fp, rows


def jev_payload(m, results, ask, expense_criteria, income_criteria, say=lambda *_: None):
    """(predictions, model) for the routed rows, one Jev decision each.

    The state is what Sonnet's prompt holds for the row, anonymised the same
    way within its month: date, type, amount, counterparty, the first 80
    characters of the description and the pot hint, plus the rule-decided
    rows of the same counterparty in that month with their categories.
    """
    from automation.data_anonymizer import anonymize_batch_for_ai
    from finance_core import tx_features as tf
    from finance_core.pot_links import pot_hints
    savings = set(tf.account_roles().get("savings", []))
    by_label = defaultdict(list)
    for r in m.records:
        by_label[r.label].append(r)
    preds, model, asked = [], None, 0
    total = sum(1 for r in m.records if _is_routed(results[r.index]))
    for label in sorted(by_label, key=_label_key):
        recs = by_label[label]
        anon, _ = anonymize_batch_for_ai([r.tx for r in recs])
        routed = [i for i, r in enumerate(recs) if _is_routed(results[r.index])]
        hints = pot_hints([r.tx for r in recs], routed, savings) if savings else {}
        for i in routed:
            a = anon[i]
            kind = "INCOME" if a.get("credit_debit_indicator") == "CRDT" else "EXPENSE"
            context = [{"type": "INCOME" if anon[j].get("credit_debit_indicator") == "CRDT" else "EXPENSE",
                        "amount_eur": round(float(anon[j].get("transaction_amount") or 0), 2),
                        "category": results[recs[j].index].category}
                       for j in range(len(recs))
                       if j not in routed and anon[j].get("creditor") == a.get("creditor")]
            state = {"transaction": {
                "date": a.get("booking_date", ""), "type": kind,
                "amount_eur": round(float(a.get("transaction_amount") or 0), 2),
                "counterparty": a.get("creditor", ""),
                "description": (a.get("remittance_information") or "")[:80],
                "hint": hints.get(i, "-")},
                "same_counterparty_this_month": context}
            block = recs[i].group[3]
            got = ask(state, jev_questions(income_criteria if block == "income" else expense_criteria))
            model = got.get("model") or model
            preds.append({"id": recs[i].index, "category": got["category"],
                          "confidence": got["confidence"], "nouls": got.get("nouls", {})})
            asked += 1
            if asked % 100 == 0:
                say(f"  jev: {asked}/{total} rows")
    return preds, model


def jev_questions(criteria):
    import jev_client
    return jev_client.questions(criteria)


def jev_criteria():
    """Per block, {category: description} from the category lists and the
    example rules Sonnet's prompt shows (the first 30)."""
    import jev_client
    from automation.ai_categorizer import get_example_rules_for_ai
    from constants import CATEGORIZATION_RULES_EXPENSE, CATEGORIZATION_RULES_INCOME
    from finance_core.categorization_engine import ai_category_options
    expense, income = ai_category_options()
    examples = dict(list(get_example_rules_for_ai(
        {**CATEGORIZATION_RULES_EXPENSE, **CATEGORIZATION_RULES_INCOME}).items())[:30])
    return (jev_client.category_descriptions(list(expense), examples),
            jev_client.category_descriptions(list(income), examples))


def read_key(path):
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                key = f.read().strip()
        except FileNotFoundError:
            raise InputError("the OpenRouter key file does not exist") from None
    else:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise InputError("no OpenRouter key (--openrouter-key-file or OPENROUTER_API_KEY)")
    return key


def run_jev(args, m, local_rules, say):
    import jev_client
    key = read_key(args.openrouter_key_file)
    session = jev_client.new_session()
    if not jev_client.zdr_ok(session):
        raise InputError("Jev 1.13 at TypeSafe is not on OpenRouter's zero data retention list; "
                         "nothing was sent")
    say("")
    say("zero data retention confirmed for typesafe/jev-1.13 at TypeSafe")
    results = asyncio.run(categorise(rules_engine(local_rules), m.records, None, lambda *_: None))
    expense, income = jev_criteria()
    try:
        preds, model = jev_payload(m, results, lambda st, qs: jev_client.decide(session, key, st, qs),
                                   expense, income, say)
    except jev_client.JevError as exc:
        raise InputError(str(exc)) from None
    fp, _ = rows_payload(m, results)
    say(f"jev answered {sum(1 for p in preds if p['category'])} of {len(preds)} routed rows "
        f"(model {model})")
    write_shadow_file(args.jev_out, "predictions", fp, preds, say, arm="jev", split="any",
                      local=False, model=model)
    return 0


def write_shadow_file(path, kind, fp, rows, say, **extra):
    from shadow_eval import write_private_jsonl
    write_private_jsonl(path, {"kind": kind, **extra, "fingerprint": fp}, rows)
    say(f"{kind} written to {path} (0600, {len(rows)} lines, not shown)")


def load_exports(paths):
    from finance_core.csv_helper import load_transactions_from_csv
    from finance_core.ledger import collapse_within_upload
    files = []
    with tempfile.TemporaryDirectory() as tmp:       # older csv_helpers rewrote their input
        for i, path in enumerate(paths):
            copy = os.path.join(tmp, f"{i}.csv")
            shutil.copy(path, copy)
            files.append(load_transactions_from_csv(copy))
    return collapse_within_upload(files)


def service_account_client(path_arg):
    import gspread
    from google.oauth2.service_account import Credentials
    path = path_arg or "src/config/google_service_account.json"
    candidates = [path] if os.path.isabs(path) else [os.path.join(PROJECT_ROOT, path),
                                                     os.path.join("/app", path)]
    found = next((p for p in candidates if os.path.exists(p)), None)
    if not found:
        raise FileNotFoundError("service account key not found; pass --credentials")
    creds = Credentials.from_service_account_file(found, scopes=[
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"])
    return gspread.authorize(creds)


def run(args, counter):
    say = print
    from finance_core.categorization_engine import ai_category_options
    expense, income = ai_category_options()
    valid = {"expenses": set(expense), "income": set(income)}
    mapping = dict(args.map or [])

    local_rules = load_rules_file(args.local_rules) if args.local_rules else []
    if args.local_rules:
        say(f"local rules: {len(local_rules)} loaded")
    if args.account_roles:
        from finance_core.tx_features import ROLES, use_account_roles
        roles = load_account_roles(args.account_roles)
        use_account_roles(roles)
        say("account roles: " + ", ".join(f"{r} {len(roles.get(r, []))}" for r in ROLES)
            + " (numbers not shown)")

    txs, collapsed = load_exports(args.csv)
    gc = service_account_client(args.credentials)
    if args.sheet:
        picked = sorted(args.sheet, key=lambda p: _label_key(p[0]))
    else:
        picked, ignored = select_sheets(gc.list_spreadsheet_files(), set(args.years.split(",")),
                                        set(args.only.split(",")) if args.only else None)
        say(f"sheets: {len(picked)} selected, {ignored} others ignored")
    say("layout:")
    sheet_rows = read_sheets(gc, picked, args.tab, say)
    m = match_rows(txs, sheet_rows, valid, mapping)
    m.counts["collapsed"] = collapsed
    say("")
    for line in format_matching(m):
        say(line)
    if args.rules:
        import rule_coverage as rc
        cov = rc.rule_coverage(m.records, m.truths, txs, rc.spaarpot_names(), since=args.recent_from,
                               local_rules=local_rules if args.local_rules else None,
                               cuts=dict(args.amount_cuts or []))
        say("")
        for line in rc.format_rule_coverage(cov):
            say(line)
        if args.names_out:
            rc.write_names(cov, args.names_out)
            say(f"names written to {args.names_out} (not shown)")
        if args.draft_out:
            rc.write_draft(cov, args.draft_out)
            say(f"draft written to {args.draft_out} (not shown)")
        return 0
    if args.jev_out:
        return run_jev(args, m, local_rules, say)
    if args.export_out:
        results = asyncio.run(categorise(rules_engine(local_rules), m.records, None, lambda *_: None))
        fp, rows = export_payload(m, results)
        say("")
        say(f"rows the rules send to the AI: {sum(1 for r in rows if r['routed'])} of {len(rows)}")
        write_shadow_file(args.export_out, "export", fp, rows, say)
        if args.rows_out:
            write_shadow_file(args.rows_out, "rows", *rows_payload(m, results), say)
        return 0
    if args.dry_run or not m.records:
        say("")
        say("dry run: nothing sent to the AI" if args.dry_run else "no rows to score")
        return 0

    engine = build_engine(args.model, local_rules)
    runs = []
    for n in range(1, args.runs + 1):
        say(f"\nrun {n}/{args.runs}, model {args.model}:")
        started = time.monotonic()
        results = asyncio.run(categorise(engine, m.records, args.parallel, say))
        rows = score(m.records, m.truths, results)
        runs.append(rows)
        say(f"run {n} took {(time.monotonic() - started) / 60:.1f} min")
        for line in format_report(build_report(rows), m, runs=None, brief=n > 1):
            say(line)
        if n == 1 and args.rows_out:
            write_shadow_file(args.rows_out, "rows", *rows_payload(m, results), say)
        if n == 1 and args.predictions_out:
            fp, _ = rows_payload(m, results)
            write_shadow_file(args.predictions_out, "predictions", fp, predictions_payload(m, results),
                              say, arm=args.model,
                              split="any", local=False)
    if len(runs) > 1:
        n, differ = disagreement([[r["pred"] for r in run] for run in runs])
        say(f"\nruns disagree on {differ}/{n} rows ({100 * differ / n:.1f}%)")
    if not any(_is_ai_answer(r) for r in runs[0]):
        say("the AI answered nothing: check `claude -p test` works in this container")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("csv", nargs="+", help="ASN exports covering the scored months")
    parser.add_argument("--years", default="2024,2025")
    parser.add_argument("--only", help="comma-separated labels, e.g. 03/2024,04/2024")
    parser.add_argument("--sheet", action="append", type=parse_pair, metavar="LABEL=ID",
                        help="use these sheets instead of listing them")
    parser.add_argument("--map", action="append", type=parse_pair, metavar="OLD=NEW",
                        help="map a sheet category name onto today's")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=None,
                        help="chunks in flight at once; default AI_MAX_PARALLEL_CHUNKS")
    parser.add_argument("--tab", default="Transactions")
    parser.add_argument("--credentials", help="service account key (default: src/config/google_service_account.json)")
    parser.add_argument("--src", help="a source tree to import instead of the image's")
    parser.add_argument("--dry-run", action="store_true",
                        help="read and match only; send nothing to the AI")
    parser.add_argument("--rules", action="store_true",
                        help="regex only: rule precision and where new rules would help")
    parser.add_argument("--names-out", metavar="PATH",
                        help="with --rules: write group names and IBANs here (0600), never printed")
    parser.add_argument("--recent-from", type=parse_month, metavar="MM/YYYY",
                        help="with --rules: base the proposals on the sheet months from this one "
                             "(default: the last 12)")
    parser.add_argument("--draft-out", metavar="PATH",
                        help="with --rules: write draft rules, splits and account roles here (0600)")
    parser.add_argument("--local-rules", metavar="PATH",
                        help="the household's rules file (private); without it no local rules run")
    parser.add_argument("--account-roles", metavar="PATH",
                        help="private file, one account per line: role, then IBAN")
    parser.add_argument("--amount-cuts", action="append", type=parse_cuts, metavar="ID=A,B,..",
                        help="with --rules: per cut, what a group's rows from it up and below it are")
    parser.add_argument("--rows-out", metavar="PATH",
                        help="shadow-eval: write the rows file (0600; no transaction content)")
    parser.add_argument("--predictions-out", metavar="PATH",
                        help="shadow-eval: write run 1's answers on the routed rows (0600)")
    parser.add_argument("--export-out", metavar="PATH",
                        help="shadow-eval: rules only, no AI; write every scored row with its "
                             "text for the local arms (0600, never printed; owner-run)")
    parser.add_argument("--jev-out", metavar="PATH",
                        help="shadow-eval: rules only, then hosted Jev on the routed rows (ZDR checked "
                             "first); write its answers here (0600)")
    parser.add_argument("--openrouter-key-file", metavar="PATH",
                        help="with --jev-out: the OpenRouter key (default: OPENROUTER_API_KEY)")
    parser.add_argument("--debug", action="store_true",
                        help="show tracebacks; may print row content")
    args = parser.parse_args(argv)
    if args.amount_cuts and not args.rules:
        parser.error("--amount-cuts works with --rules only")
    if args.export_out and (args.rules or args.dry_run or args.predictions_out):
        parser.error("--export-out runs the rules alone; not with --rules, --dry-run or --predictions-out")
    if args.jev_out and (args.rules or args.dry_run or args.predictions_out or args.export_out):
        parser.error("--jev-out runs alone; not with --rules, --dry-run, --predictions-out or --export-out")
    if args.predictions_out and (args.rules or args.dry_run):
        parser.error("--predictions-out needs an AI run")
    if args.src:
        sys.path.insert(0, args.src)
    counter = install_quiet_logging()
    code = guarded(lambda: run(args, counter), debug=args.debug)
    for line in counter.summary():
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
