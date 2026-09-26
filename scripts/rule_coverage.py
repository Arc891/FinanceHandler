"""
Rule coverage for eval_categoriser --rules: where more regex rules would help.

Runs the regex pass alone over the hand-checked months and reports:

- each rule's precision, overall and per year;
- what the rows hold beyond name and text (time of day, transaction code);
- the rows no rule covers, grouped by counterparty name and by IBAN, each
  group pure or mixed, stable across years or not, and for a mixed group the
  single feature that splits it best, scored leave-one-out so a split that
  only fits its own rows does not win;
- whether pot transfers can be linked to the purchases they cover: a transfer
  from the savings account equals one purchase, or the exact sum of several;
- a proposed decision per name group from its rows in the last 12 sheet
  months (keep, split on one feature, review, gd or drop), what each would
  write there, and suggested roles for the household's own accounts;
- a projection over those months of the rows per month that would still
  need the user, today and with the proposals.

The printed report holds counts, category and feature names, rule patterns
(which are code) and anonymous group ids only. Names, IBANs, keywords and
amount thresholds go to files only the user reads (0600). Nothing is sent to
the AI.
"""

import os
import re
from collections import Counter, defaultdict
from types import SimpleNamespace

from eval_categoriser import _name, _pct, score
from finance_core.tx_features import (  # noqa: F401  (re-exported for the tests)
    remittance_text as _remittance, tx_amount, tx_cents as _cents, tx_code, tx_day as _day,
    tx_direction, tx_hour, tx_weekend, tx_words, tx_year,
)

GROUP_MIN = 3             # rows a counterparty group needs to be listed
PURE_SHARE = 0.9          # a group this uniform is pure
READY_SHARE = 0.8         # a savings account this uniform is recognised as one
KEEP_SHARE = 0.95         # a group this uniform, not shifting, is proposed as a plain rule
GD_SHARE = 0.25           # a group this much Goeie doelen is proposed as `gd`
GROUPS_SHOWN = 30         # groups listed per grouping
MIRROR_DAYS = 7           # an opposite row this close is a mirror
PATTERN_MAX = 60          # longest rule pattern printed
USEFUL_GAIN = 0.10        # a split (leave-one-out) must beat the top category's share by this much
KEYWORD_CANDIDATES = 40   # most frequent words tried as a keyword split
LINK_WINDOWS = (7, 14, 31)  # days between a pot transfer and the purchases it covers
LINK_MAX_ITEMS = 4        # purchases one pot transfer may cover
RECENT_MONTHS = 12        # proposals rest on the last this many sheet months, unless given a start
REVIEW_SHARE = 0.8        # a group nothing separates is marked from this share; below it, the AI decides
RECURRING_MONTHS = 3      # an amount paid in this many different months is a recurring one
SPLIT_EXCLUDED = ("year",)  # a future row is always in a new year, so no rule splits on it
# Rows left to the AI, at the last Sonnet run's rates (2026-09-26, 0.75
# threshold): 529 of 990 flagged, 155 of 990 written wrong and unflagged.
AI_FLAG_RATE = 529 / 990
AI_SILENT_WRONG_RATE = 155 / 990
AI = "ai"                 # a split branch that leaves the row to the AI
DROP_WHY = {"not seen": "not seen in the window",
            "too few": f"fewer than {GROUP_MIN} rows in the window",
            "mixed": f"below {100 * REVIEW_SHARE:.0f}% one category, nothing separates the rows"}

UIT_SPAARPOTJE = "Uit spaarpotje"
GOEIE_DOELEN = "Goeie doelen"
SPAARREKENING = "Spaarrekening"
VRIJ_GELD = "Persoonlijk vrij geld"

KEY_TOKEN = re.compile(r"[^\W_]+")      # letters and digits, accented ones too
# Between two key words in a pattern: what KEY_TOKEN splits on, and any
# one-letter word the key left out (an initial: `jan p. bakker`).
KEY_GAP = r"[\W_]+(?:[^\W_][\W_]+)*"


# ── reading a row ───────────────────────────────────────────────────────────

def _counterparty(tx):
    return ((tx.get("creditor") or {}).get("name") or
            (tx.get("debtor") or {}).get("name") or "").strip()


def _iban(tx):
    return (tx.get("counterparty_iban") or "").strip()


def merchant_key(tx) -> str:
    """A counterparty's name without branch numbers, places or case.

    Words up to the first one holding a digit, at most two of them, so
    `HEMA 5678 AMSTERDAM` and `hema` share a key. Without a name, the start
    of the remittance text stands in.
    """
    text = _counterparty(tx) or _remittance(tx)
    words = []
    for token in KEY_TOKEN.findall(text.lower()):
        if any(ch.isdigit() for ch in token) or len(words) == 2:
            break
        if len(token) > 1:
            words.append(token)
    return " ".join(words)


def spaarpot_names():
    try:
        from config.spaarpot_uuid_map import SPAARPOT_UUID_MAP
    except ImportError:
        return []
    return list(SPAARPOT_UUID_MAP.values())


def feature_probe(pairs):
    """How often a time of day appears, and the true categories per bank code."""
    codes = defaultdict(Counter)
    for tx, truth in pairs:
        codes[tx_code(tx)][truth] += 1
    return dict(rows=len(pairs), with_time=sum(1 for tx, _ in pairs if tx_hour(tx) is not None),
                codes=dict(codes))


# ── splitting a mixed group ─────────────────────────────────────────────────

def _top(counter):
    """The most common key with a positive count; ties go alphabetically."""
    return min(((k, n) for k, n in counter.items() if n > 0), key=lambda kv: (-kv[1], kv[0]))[0]


def _constant(rows):
    return (lambda tx: "all"), (lambda v: "any")


def _key_threshold(rows, value_of, fmt):
    """One cut on a number, chosen in-sample; rows without the number are a branch of their own."""
    have = sorted(((value_of(tx), t) for tx, t in rows if value_of(tx) is not None),
                  key=lambda p: p[0])
    below, above = Counter(), Counter(t for _, t in have)
    best = None
    for k in range(len(have) - 1):
        value, truth = have[k]
        below[truth] += 1
        above[truth] -= 1
        if have[k + 1][0] == value:
            continue
        correct = max(below.values()) + max(above.values())
        if best is None or correct > best[0]:
            best = (correct, (value + have[k + 1][0]) / 2)
    if best is None:
        return (lambda tx: None if value_of(tx) is None else "all"), (lambda v: "none" if v is None else "any")
    cut = best[1]

    def key(tx):
        v = value_of(tx)
        return None if v is None else v >= cut
    return key, lambda v: {None: "none", False: f"below {fmt(cut)}", True: f"from {fmt(cut)}"}[v]


def _key_recurring(rows):
    """Whether the amount is one the group paid in RECURRING_MONTHS different months.

    A fixed transfer that changed once (free money went up) recurs at both
    amounts.
    """
    months = defaultdict(set)
    for tx, _ in rows:
        amount, day = tx_amount(tx), _day(tx)
        if amount is not None and day is not None:
            months[amount].add((day.year, day.month))
    fixed = {a for a, seen in months.items() if len(seen) >= RECURRING_MONTHS}
    if not fixed:
        return _constant(rows)
    shown = "/".join(f"{a:.2f}" for a in sorted(fixed))
    return (lambda tx: tx_amount(tx) in fixed), (lambda v: f"{'at' if v else 'not at'} {shown}")


def _key_keyword(rows, words_of):
    """The word whose presence best splits the rows; ties go alphabetically."""
    counts = Counter(w for tx, _ in rows for w in words_of(tx))
    tried = sorted((w for w, n in counts.items() if 2 <= n < len(rows)),
                   key=lambda w: (-counts[w], w))[:KEYWORD_CANDIDATES]
    best = None
    for word in sorted(tried):
        present, absent = Counter(), Counter()
        for tx, t in rows:
            (present if word in words_of(tx) else absent)[t] += 1
        correct = max(present.values()) + max(absent.values())
        if best is None or correct > best[0]:
            best = (correct, word)
    if best is None:
        return _constant(rows)
    word = best[1]
    return (lambda tx: word in words_of(tx)), (lambda v: f"with {word!r}" if v else "without")


def _features(words_of):
    """(name, key) in order of preference when two score the same.

    A key is fitted on rows and returns (value_of, describe): the branch a
    row falls in, and how to name a branch (which may hold an amount or a
    word, so it is for the private draft only).
    """
    return (
        ("direction", lambda rows: (tx_direction, str)),
        ("code", lambda rows: (tx_code, str)),
        ("weekend", lambda rows: (tx_weekend,
                                  lambda v: {True: "weekend", False: "weekday"}.get(v, "no date"))),
        ("time of day", lambda rows: _key_threshold(rows, tx_hour, lambda c: f"{c:.1f}h")),
        ("recurring amount", _key_recurring),
        ("amount", lambda rows: _key_threshold(rows, tx_amount, lambda c: f"{c:.2f}")),
        ("keyword", lambda rows: _key_keyword(rows, words_of)),
        # Last, so any feature a rule could use wins a tie: a year split means
        # the booking habit changed, and the latest year is the one to follow.
        ("year", lambda rows: (tx_year, str)),
    )


def _fit(rows, key):
    """Each branch's top category; a value not seen in fitting gets the overall top."""
    value_of, describe = key(rows)
    by = defaultdict(Counter)
    for tx, t in rows:
        by[value_of(tx)][t] += 1
    default = _top(Counter(t for _, t in rows))
    table = {v: _top(c) for v, c in by.items()}
    detail = "; ".join(f"{describe(v)} -> {table[v]} ({sum(by[v].values())})"
                       for v in sorted(by, key=str))
    return SimpleNamespace(predict=lambda tx: table.get(value_of(tx), default), detail=detail,
                           value_of=value_of, describe=describe, branches=dict(by))


def _leave_one_out(rows, key):
    correct = 0
    for i, (tx, truth) in enumerate(rows):
        correct += _fit(rows[:i] + rows[i + 1:], key).predict(tx) == truth
    return correct / len(rows)


def best_split(rows, exclude=()):
    """Which single feature predicts a group's category best, leave-one-out.

    The baseline is the top category's share, what a plain rule scores. It
    is not taken leave-one-out: in a balanced group that scores 0 (holding
    out a row hands the majority to the other category), which would make
    any split look like a gain. `detail` (the fitted split, which may hold
    an amount or a word) is for the private draft only; `fit` is the best
    feature fitted on all rows.
    """
    words = {id(tx): tx_words(tx) for tx, _ in rows}
    features = [(name, key) for name, key in _features(lambda tx: words[id(tx)]) if name not in exclude]
    truths = Counter(t for _, t in rows)
    majority = truths[_top(truths)] / len(rows)
    scores = {name: _leave_one_out(rows, fit) for name, fit in features}
    top = max(scores.values())
    best = next(name for name, _ in features if scores[name] == top)
    if top - majority < USEFUL_GAIN:
        best = None
    fit = _fit(rows, dict(features)[best]) if best else None
    return dict(majority=majority, features=scores, best=best, gain=top - majority,
                detail=fit.detail if fit else "", fit=fit)


# ── linking pot transfers to the purchases they cover ──────────────────────

def savings_accounts(pairs):
    """IBANs whose incoming rows are, by the sheets, mostly Spaarrekening."""
    seen = defaultdict(Counter)
    for tx, truth in pairs:
        if _iban(tx) and tx_direction(tx) == "in":
            seen[_iban(tx)][truth] += 1
    return {iban for iban, c in seen.items()
            if c[SPAARREKENING] >= GROUP_MIN and c[SPAARREKENING] / sum(c.values()) >= READY_SHARE}


def subsets_summing(values, target, max_items, limit):
    """Up to `limit` distinct sets of at most `max_items` keys whose values sum to target.

    Values are positive integers (cents); keys are sortable. Pairs are
    indexed by sum, so four items cost a pair of pairs, not a 4-deep loop.
    """
    keys = sorted(values)
    found = []

    def add(keyset):
        if keyset not in found:
            found.append(frozenset(keyset))
        return len(found) >= limit

    for k in keys:
        if values[k] == target and add({k}):
            return found
    if max_items < 2:
        return found
    pairs = defaultdict(list)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            pairs[values[a] + values[b]].append((a, b))
    for a, b in pairs.get(target, []):
        if add({a, b}):
            return found
    if max_items >= 3:
        for a in keys:
            for b, c in pairs.get(target - values[a], []):
                if a < b and add({a, b, c}):
                    return found
    if max_items >= 4:
        for total, first in pairs.items():
            for a, b in first:
                for c, d in pairs.get(target - total, []):
                    if b < c and add({a, b, c, d}):
                        return found
    return found


def find_links(txs, truth_of, savings, window, max_items):
    """Link each transfer in from a savings account to the purchases it covers.

    A transfer links only when exactly one set of purchases (outgoing, not
    to a savings account, within `window` days) sums to it; a purchase two
    transfers both claim is linked to neither. Claimed purchases are scored
    against the sheets: `explained` were Uit spaarpotje, `claimed_other`
    counts the rest by true category.
    """
    days = [_day(t) for t in txs]
    cents = [_cents(t) for t in txs]
    usable = [i for i in range(len(txs)) if days[i] is not None and cents[i]]
    covers = [i for i in usable if tx_direction(txs[i]) == "in" and _iban(txs[i]) in savings]
    purchases = [i for i in usable if tx_direction(txs[i]) == "out" and _iban(txs[i]) not in savings]
    stats = dict(covers=len(covers), linked=0, ambiguous=0, none=0, conflict=0, explained=0,
                 claimed_other=Counter(), unscored=0,
                 targets=sum(1 for truth in truth_of.values() if truth == UIT_SPAARPOTJE))
    solutions = {}
    for c in covers:
        near = {i: cents[i] for i in purchases if abs((days[i] - days[c]).days) <= window}
        found = subsets_summing(near, cents[c], max_items, limit=2)
        if len(found) == 1:
            solutions[c] = found[0]
        elif found:
            stats["ambiguous"] += 1
        else:
            stats["none"] += 1
    claims = Counter(i for keyset in solutions.values() for i in keyset)
    for keyset in solutions.values():
        if any(claims[i] > 1 for i in keyset):
            stats["conflict"] += 1
            continue
        stats["linked"] += 1
        for i in keyset:
            truth = truth_of.get(id(txs[i]))
            if truth is None:
                stats["unscored"] += 1
            elif truth == UIT_SPAARPOTJE:
                stats["explained"] += 1
            else:
                stats["claimed_other"][truth] += 1
    return stats


def account_roles(pairs, savings):
    """Suggested roles: savings accounts, and the accounts free money goes to."""
    roles = {}
    for iban in savings:
        rows = [tx for tx, t in pairs if _iban(tx) == iban and t == SPAARREKENING]
        roles[iban] = dict(role="savings", rows=len(rows), names=Counter(_counterparty(tx) for tx in rows))
    personal = defaultdict(list)
    for tx, truth in pairs:
        if _iban(tx) and tx_direction(tx) == "out" and truth == VRIJ_GELD:
            personal[_iban(tx)].append(tx)
    for iban, rows in personal.items():
        if len(rows) >= 2 and iban not in roles:
            roles[iban] = dict(role="personal", rows=len(rows), names=Counter(_counterparty(tx) for tx in rows))
    return roles


# ── the analysis ────────────────────────────────────────────────────────────

def _mirrors(txs, spaarpots):
    """Per tx index: (days to the nearest mirror, mirror mentions a pot) or None."""
    by_amount = defaultdict(list)
    for i, tx in enumerate(txs):
        amount = tx_amount(tx)
        if amount is not None:
            by_amount[amount].append(i)
    found = {}
    for idxs in by_amount.values():
        for i in idxs:
            best = None
            for j in idxs:
                a, b = txs[i], txs[j]
                if j == i or a.get("credit_debit_indicator") == b.get("credit_debit_indicator"):
                    continue
                da, db = _day(a), _day(b)
                if da is None or db is None or abs((da - db).days) > MIRROR_DAYS:
                    continue
                text = _remittance(b).lower()
                pot = any(name.lower() in text for name in spaarpots if name)
                gap = abs((da - db).days)
                if best is None or (gap, not pot) < (best[0], not best[1]):
                    best = (gap, pot)
            found[i] = best
    return found


def _stability(members):
    """`stable` if every year with 2+ rows has the same top category."""
    by_year = defaultdict(Counter)
    for rec, truth in members:
        by_year[rec.label[3:]][truth] += 1
    years = [c for c in by_year.values() if sum(c.values()) >= 2]
    if len(years) < 2:
        return "one year"
    return "stable" if len({_top(c) for c in years}) == 1 else "shifts"


def _groups(members, key_of, prefix):
    by_key = defaultdict(list)
    for rec, truth in members:
        key = key_of(rec.tx)
        if key:
            by_key[key].append((rec, truth))
    groups = []
    for key, rows in by_key.items():
        if len(rows) < GROUP_MIN:
            continue
        truths = Counter(t for _, t in rows)
        pure = truths.most_common(1)[0][1] / len(rows) >= PURE_SHARE
        group = dict(key=key, rows=len(rows), months=len({r.label for r, _ in rows}),
                     truths=truths, pure=pure, stability=_stability(rows), members=rows,
                     names=Counter(_counterparty(r.tx) or "(no name)" for r, _ in rows))
        if not pure:
            group["split"] = best_split([(r.tx, t) for r, t in rows])
        groups.append(group)
    groups.sort(key=lambda g: (-g["rows"], g["key"]))
    for n, g in enumerate(groups, 1):
        g["id"] = f"{prefix}{n:02d}"
    return groups


def _latest_top(members):
    by_year = defaultdict(Counter)
    for rec, truth in members:
        by_year[rec.label[3:]][truth] += 1
    return _top(by_year[max(by_year)])


def _month_order(label):
    return label[3:], label[:2]


def _window(records, since=None):
    """The sheet months ("MM/YYYY") present in the data from `since`, or the last RECENT_MONTHS."""
    labels = sorted({r.label for r in records}, key=_month_order)
    if since:
        return [label for label in labels if _month_order(label) >= _month_order(since)]
    return labels[-RECENT_MONTHS:]


def _conditional(pairs, known):
    """A rule that splits on one feature, or None when no branch gets a category.

    A branch gets its top category when it has GROUP_MIN rows at KEEP_SHARE
    or more; any other branch, and a value not seen here, goes to the AI.
    """
    split = best_split(pairs, exclude=SPLIT_EXCLUDED)
    if not split["best"]:
        return None
    fit = split["fit"]
    outcomes = {}
    for value, truths in fit.branches.items():
        top, n = _top(truths), sum(truths.values())
        outcomes[value] = top if n >= GROUP_MIN and truths[top] / n >= KEEP_SHARE and known(top) else AI
    if all(o == AI for o in outcomes.values()):
        return None
    order = sorted(outcomes, key=str)
    value_of = fit.value_of
    return dict(feature=split["best"], outcome=lambda tx: outcomes.get(value_of(tx), AI),
                outcomes=[outcomes[v] for v in order],
                detail="; ".join(f"{fit.describe(v)} -> {outcomes[v]} ({sum(fit.branches[v].values())})"
                                 for v in order))


def _decider(decision, category, split):
    """(category or None for the AI, marked) for a row the draft's pattern catches."""
    if decision == "review":
        return lambda tx: (category, True)
    if decision == "gd":
        return lambda tx: (GOEIE_DOELEN, tx_code(tx) == "BEA")
    if decision == "split":
        def decide(tx):
            outcome = split["outcome"](tx)
            return (None if outcome == AI else outcome), False
        return decide
    return lambda tx: (category, False)   # keep; for drop, what it would have caught


def _draft(uncovered, name_groups, window):
    """A proposed decision per name group and direction, tried on every uncovered row.

    Decided on the group's rows in `window`: `drop` when it has none there
    or fewer than GROUP_MIN, then `gd`, `keep`, a `split` on one feature a
    rule can check, and when nothing separates the rows `review` from
    REVIEW_SHARE one category, else `drop` (the AI decides). A group
    that shifted between years follows its latest year. `hits` and
    `correct` count every uncovered row in `window` the pattern would
    write a category for, its own and other groups'.
    """
    from constants import ExpenseCategory, IncomeCategory
    from finance_core.categorization_rules import search_text
    inside = set(window)
    drafts = []
    for g in name_groups:
        for direction in ("out", "in"):
            members = [(r, t) for r, t in g["members"] if tx_direction(r.tx) == direction]
            if len(members) < GROUP_MIN:
                continue
            enum = IncomeCategory if direction == "in" else ExpenseCategory
            names = {m.value: f"{enum.__name__}.{m.name}" for m in enum}
            recent = [(r, t) for r, t in members if r.label in inside]
            basis = recent or members
            truths = Counter(t for _, t in basis)
            stability = _stability(basis)
            category = _latest_top(basis) if stability == "shifts" else _top(truths)
            share = truths[_top(truths)] / len(basis)
            split, why = None, ""
            if not recent:
                decision, why = "drop", "not seen"
            elif len(recent) < GROUP_MIN:
                decision, why = "drop", "too few"
            elif truths[GOEIE_DOELEN] / len(recent) >= GD_SHARE:
                decision, category = "gd", GOEIE_DOELEN
            elif share >= KEEP_SHARE and stability != "shifts" and category == _top(truths):
                decision = "keep"
            else:
                split = _conditional([(r.tx, t) for r, t in recent], lambda c: c in names)
                if split:
                    decision = "split"
                elif share >= REVIEW_SHARE:
                    decision = "review"
                else:
                    decision, why = "drop", "mixed"
            if decision in ("keep", "review", "gd") and category not in names:
                continue
            pattern = r"\b" + KEY_GAP.join(re.escape(w) for w in g["key"].split()) + r"\b"
            rx = re.compile(pattern, re.IGNORECASE)
            decide = _decider(decision, category, split)
            written = [(decide(r.tx)[0], t) for r, t in uncovered if r.label in inside and
                       tx_direction(r.tx) == direction and rx.search(search_text(r.tx))]
            written = [(c, t) for c, t in written if c is not None]
            drafts.append(dict(id=g["id"], key=g["key"], direction=direction, decision=decision, why=why,
                               pattern=pattern, category="-" if split else category,
                               member=None if split else names.get(category), split=split, decide=decide,
                               rows=len(members), recent=len(recent), share=share, truths=truths,
                               stability=stability, hits=len(written),
                               correct=sum(c == t for c, t in written), names=g["names"]))
    return drafts


def _projection(records, fired, rows, drafts, window):
    """Rows in `window`, today and with the proposals: by rule, plain, marked, to the AI.

    With the proposals, an uncovered row takes the first draft (not dropped)
    of its direction whose pattern matches it.
    """
    from finance_core.categorization_rules import search_text
    inside = set(window)
    active = [(d, re.compile(d["pattern"], re.IGNORECASE)) for d in drafts if d["decision"] != "drop"]
    today, proposed = Counter(), Counter()
    for rec, rule, row in zip(records, fired, rows):
        if rec.label not in inside:
            continue
        if rule:
            for c in (today, proposed):
                c["rules"] += 1
                c["rules_wrong"] += not row["correct"]
            continue
        today["ai"] += 1
        text, direction = search_text(rec.tx), tx_direction(rec.tx)
        draft = next((d for d, rx in active if d["direction"] == direction and rx.search(text)), None)
        category, marked = draft["decide"](rec.tx) if draft else (None, False)
        if category is None:
            proposed["ai"] += 1
        elif marked:
            proposed["marked"] += 1
        else:
            proposed["plain"] += 1
            proposed["plain_wrong"] += category != row["truth"]
    keys = ("rules", "rules_wrong", "plain", "plain_wrong", "marked", "ai")
    return dict(months=len(window), today={k: today[k] for k in keys},
                proposed={k: proposed[k] for k in keys})


def _watch(pairs, fired, rows, drafts):
    """Goeie doelen recall: donations the rules catch and the proposals would add."""
    caught = sum(1 for rule, row in zip(fired, rows)
                 if rule and row["correct"] and row["truth"] == GOEIE_DOELEN)
    proposed = [d for d in drafts if d["category"] == GOEIE_DOELEN and d["decision"] != "drop"]
    return dict(total=sum(1 for _, t in pairs if t == GOEIE_DOELEN), by_rules=caught,
                by_decisions=sum(d["truths"][GOEIE_DOELEN] for d in proposed),
                marked_other=sum(d["rows"] - d["truths"][GOEIE_DOELEN] for d in proposed))


def rule_coverage(records, truths, txs, spaarpot_names=(), since=None):
    """The regex pass alone, scored, plus what the uncovered rows have in common.

    Proposals rest on the sheet months from `since` ("MM/YYYY"), or the last
    RECENT_MONTHS without it.
    """
    from finance_core.categorization_rules import first_matching_rule
    fired = [first_matching_rule(r.tx) for r in records]
    results = [SimpleNamespace(category=rule.category.value, method="regex", confidence=1.0)
               if rule else None for rule in fired]
    rows = score(records, truths, results)
    pairs = [(rec.tx, row["truth"]) for rec, row in zip(records, rows)]

    rules = {}
    uncovered = []
    for rec, rule, row in zip(records, fired, rows):
        if rule is None:
            uncovered.append((rec, row["truth"]))
            continue
        hit = rules.setdefault(rule.pattern, dict(hits=0, correct=0, wrong=Counter(), years={}))
        year = hit["years"].setdefault(rec.label[3:], [0, 0])
        hit["hits"] += 1
        year[0] += 1
        if row["correct"]:
            hit["correct"] += 1
            year[1] += 1
        else:
            hit["wrong"][row["truth"]] += 1

    position = {id(tx): i for i, tx in enumerate(txs)}
    near = _mirrors(txs, list(spaarpot_names))
    mirrors = {}
    for rec, truth in uncovered:
        m = mirrors.setdefault(truth, dict(rows=0, mirrored=0, same_day=0, spaarpot=0))
        m["rows"] += 1
        hit = near.get(position.get(id(rec.tx)))
        if hit:
            m["mirrored"] += 1
            m["same_day"] += hit[0] == 0
            m["spaarpot"] += hit[1]

    truth_of = {id(tx): truth for tx, truth in pairs}
    savings = savings_accounts(pairs)
    name_groups = _groups(uncovered, merchant_key, "N")
    window = _window(records, since)
    drafts = _draft(uncovered, name_groups, window)
    return dict(
        scored=len(records),
        rules=rules,
        features=feature_probe(pairs),
        uncovered=Counter(t for _, t in uncovered),
        name_groups=name_groups,
        iban_groups=_groups(uncovered, _iban, "I"),
        mirrors=mirrors,
        savings=savings,
        links={(w, k): find_links(txs, truth_of, savings, w, k)
               for w in LINK_WINDOWS for k in range(1, LINK_MAX_ITEMS + 1)},
        accounts=account_roles(pairs, savings),
        window=window,
        draft=drafts,
        projection=_projection(records, fired, rows, drafts, window),
        watch=_watch(pairs, fired, rows, drafts),
    )


# ── the printed report: counts and names of things only ────────────────────

def _share(counter, n):
    return ", ".join(f"{_name(c)} {100 * k / n:.0f}%" for c, k in counter.most_common(3))


def _years(years):
    return ", ".join(f"{y} {ok}/{n}" for y, (n, ok) in sorted(years.items()))


def _span(window):
    return f"{window[0]} to {window[-1]} ({len(window)} sheet months)" if window else "(no months)"


def format_rule_coverage(cov):
    lines = [f"rule coverage (regex only, nothing sent to the AI), {cov['scored']} rows scored:"]
    covered = sum(h["hits"] for h in cov["rules"].values())
    right = sum(h["correct"] for h in cov["rules"].values())
    lines.append(f"  covered by a rule: {_pct(covered, right)} correct; "
                 f"not covered: {sum(cov['uncovered'].values())}")

    f = cov["features"]
    lines.append(f"what the rows hold: a time of day in {f['with_time']}/{f['rows']} rows; "
                 "true categories per transaction code:")
    for code, truths in sorted(f["codes"].items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(truths.values())
        lines.append(f"  {code}: {n} rows: {_share(truths, n)}")

    lines.append("rules that fired (pattern: hits, correct [per year]; true category when wrong):")
    for pattern, h in sorted(cov["rules"].items(), key=lambda kv: (kv[1]["correct"] - kv[1]["hits"], kv[0])):
        shown = pattern if len(pattern) <= PATTERN_MAX else pattern[:PATTERN_MAX] + "..."
        wrong = f"; wrong: {_share(h['wrong'], h['hits'] - h['correct'])}" if h["wrong"] else ""
        lines.append(f"  {shown!r}: {_pct(h['hits'], h['correct'])} [{_years(h['years'])}]{wrong}")

    lines.append("not covered by any rule, per true category:")
    for cat, n in cov["uncovered"].most_common():
        lines.append(f"  {_name(cat)}: {n}")

    drafted = {d["id"] for d in cov["draft"]}
    for title, groups in (("counterparty name", cov["name_groups"]),
                          ("counterparty IBAN", cov["iban_groups"])):
        pure = [g for g in groups if g["pure"]]
        lines.append(f"uncovered rows grouped by {title} (groups of {GROUP_MIN}+ rows): "
                     f"{len(groups)} groups, {sum(g['rows'] for g in groups)} rows; "
                     f"pure (>= {100 * PURE_SHARE:.0f}% one category): {len(pure)} groups, "
                     f"{sum(g['rows'] for g in pure)} rows")
        for g in groups[:GROUPS_SHOWN]:
            kind = "pure " if g["pure"] else "mixed"
            tag = ", draft rule" if g["id"] in drafted else ""
            lines.append(f"  {g['id']} {kind} {g['rows']} rows over {g['months']} months, "
                         f"{g['stability']}{tag}: {_share(g['truths'], g['rows'])}")
            split = g.get("split")
            if split:
                if split["best"]:
                    lines.append(f"      best split: {split['best']} {100 * split['features'][split['best']]:.0f}% "
                                 f"(leave-one-out) vs {100 * split['majority']:.0f}% for the top category")
                else:
                    lines.append(f"      best split: none beats the top category "
                                 f"({100 * split['majority']:.0f}%) by {100 * USEFUL_GAIN:.0f} points")

    d = cov["draft"]
    kinds = Counter(x["decision"] for x in d)
    rows_by = Counter()
    for x in d:
        rows_by[x["decision"]] += x["recent"]
    why = Counter(x["why"] for x in d if x["decision"] == "drop")
    plain = [x for x in d if x["decision"] in ("keep", "split")]
    lines.append(f"decisions proposed per name group, from the window {_span(cov['window'])} "
                 "(change the first word in the draft file): " +
                 ", ".join(f"{k} {kinds[k]} groups ({rows_by[k]} recent rows)"
                           for k in ("keep", "split", "review", "gd", "drop")) +
                 "; drop: " + ", ".join(f"{why[k]} {text}" for k, text in DROP_WHY.items()) +
                 "; keep and split rules write "
                 f"{_pct(sum(x['hits'] for x in plain), sum(x['correct'] for x in plain))} "
                 "correct over the uncovered rows in those months")
    for x in d:
        extra = ""
        if x["split"]:
            extra = f"; split by {x['split']['feature']} -> {', '.join(x['split']['outcomes'])}"
        elif x["why"]:
            extra = f" ({DROP_WHY[x['why']]})"
        lines.append(f"  {x['id']} {x['direction']} {x['decision']}{extra}: {x['recent']} recent rows of {x['rows']}, "
                     f"top {100 * x['share']:.0f}%, {x['stability']}; writes {_pct(x['hits'], x['correct'])}")
    p = cov["projection"]
    months = p["months"] or 1
    lines.append(f"per month over the window ({p['months']} sheet months): rows that need you (marked, plus what "
                 f"the AI flags) and rows written wrong unmarked; rows left to the AI count at the last Sonnet "
                 f"run's rates ({100 * AI_FLAG_RATE:.0f}% flagged, {100 * AI_SILENT_WRONG_RATE:.0f}% wrong "
                 "unflagged), and the rows left after new rules are harder, so likely more:")
    for name in ("today", "proposed"):
        c = p[name]
        flagged = c["ai"] * AI_FLAG_RATE
        wrong = c["rules_wrong"] + c["plain_wrong"] + c["ai"] * AI_SILENT_WRONG_RATE
        lines.append(f"  {name}: {(c['marked'] + flagged) / months:.1f} rows need you "
                     f"({c['marked'] / months:.1f} marked, {flagged / months:.1f} flagged by the AI); "
                     f"{wrong / months:.1f} written wrong unmarked; of "
                     f"{sum(c[k] for k in ('rules', 'plain', 'marked', 'ai')) / months:.1f} rows: "
                     f"{c['rules'] / months:.1f} by today's rules, {c['plain'] / months:.1f} by new rules, "
                     f"{c['ai'] / months:.1f} to the AI")
    w = cov["watch"]
    lines.append(f"Goeie doelen recall (a missed donation costs a deduction): {w['total']} rows; "
                 f"today's rules catch {w['by_rules']}; the proposals add {w['by_decisions']} "
                 f"and would also mark {w['marked_other']} other rows as Goeie doelen")

    lines.append(f"pot transfer links (savings accounts found: {len(cov['savings'])}; a transfer links "
                 "when exactly one set of purchases in the window sums to it):")
    for (window, items), s in sorted(cov["links"].items()):
        wrong = sum(s["claimed_other"].values())
        detail = f" ({_share(s['claimed_other'], wrong)})" if wrong else ""
        lines.append(f"  {window} days, up to {items}: {s['covers']} transfers: {s['linked']} linked, "
                     f"{s['ambiguous']} ambiguous, {s['conflict']} in conflict, {s['none']} unmatched; "
                     f"Uit spaarpotje explained {s['explained']}/{s['targets']}; "
                     f"wrong claims {wrong}{detail}; unscored claims {s['unscored']}")

    roles = Counter(r["role"] for r in cov["accounts"].values())
    lines.append(f"account roles suggested: {roles['savings']} savings, {roles['personal']} personal "
                 "(numbers in the draft file only)")

    lines.append(f"uncovered rows with a mirror (opposite row, same amount, within {MIRROR_DAYS} days):")
    for cat, m in sorted(cov["mirrors"].items(), key=lambda kv: -kv[1]["rows"]):
        lines.append(f"  {_name(cat)}: {m['mirrored']}/{m['rows']} mirrored, "
                     f"{m['same_day']} same day, {m['spaarpot']} with a spaarpot name")
    return lines


# ── private files (0600): names, IBANs, keywords, thresholds ───────────────

def _private(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")


def _names(counter, n=5):
    return " | ".join(f"{name} ({k})" for name, k in counter.most_common(n))


def write_names(cov, path):
    """The groups' keys, names and IBANs, for the user's eyes only (0600)."""
    with _private(path) as out:
        out.write("id\tkey\trows\tcategories\tnames\n")
        for g in cov["name_groups"] + cov["iban_groups"]:
            cats = ", ".join(f"{c} {k}" for c, k in g["truths"].most_common())
            out.write(f"{g['id']}\t{g['key']}\t{g['rows']}\t{cats}\t{_names(g['names'])}\n")


def write_draft(cov, path):
    """Draft rules to edit and hand back, and what splits the mixed groups (0600)."""
    with _private(path) as out:
        w = out.write
        w("# Rule draft from eval_categoriser --rules. PRIVATE: holds names, account numbers,\n"
          "# words and amounts from your rows. Delete or fix lines, then hand back what you keep.\n\n")
        w("# 1. Decisions, one line per counterparty group. Change the FIRST word:\n"
          "#      keep    a plain rule: this category, not marked\n"
          "#      split   a rule on one feature (see branches): each branch writes its category\n"
          "#              or leaves the row to the AI (`ai`); a value not seen here goes to the AI\n"
          "#      review  this category, but always marked for you to check (multi-purpose shops)\n"
          "#      gd      Goeie doelen, catching too much rather than too little; rows that are\n"
          "#              less clearly a donation (e.g. a card payment) are marked\n"
          "#      drop    no rule; the AI decides\n"
          "#    You may also change the category or a branch. `written` is over every recent row no\n"
          "#    rule covers today, so it shows what else the pattern would catch. Proposals rest on the\n"
          f"#    window {_span(cov['window'])}: drop when a group has fewer than {GROUP_MIN}\n"
          f"#    rows there; gd at >= {100 * GD_SHARE:.0f}% donations; keep at >= {100 * KEEP_SHARE:.0f}% one "
          "category, not shifting\n"
          "#    between years; split when one feature (not the year) gives a branch of "
          f"{GROUP_MIN}+ rows at >= {100 * KEEP_SHARE:.0f}%;\n"
          f"#    review otherwise from {100 * REVIEW_SHARE:.0f}% one category, drop below it (a group that shifted\n"
          "#    takes its latest year's category). Put multi-purpose shops you know back to review.\n"
          "#    `recent` and `top share` are over those months; `categories` too (all rows for a drop).\n")
        w("# decision\tid\tdirection\tcategory\tkey\tpattern\tbranches\trecent\trows\ttop share\tstability\t"
          "written\tcategories\tnames\n")
        for d in cov["draft"]:
            cats = ", ".join(f"{c} {k}" for c, k in d["truths"].most_common())
            branches = (f"{d['split']['feature']}: {d['split']['detail']}" if d["split"]
                        else DROP_WHY.get(d["why"], "-"))
            w(f"{d['decision']}\t{d['id']}\t{d['direction']}\t{d['category']}\t{d['key']}\t{d['pattern']}\t"
              f"{branches}\t{d['recent']}\t{d['rows']}\t{100 * d['share']:.0f}%\t{d['stability']}\t"
              f"{d['correct']}/{d['hits']}\t{cats}\t{_names(d['names'], 3)}\n")

        w("\n# 2. Mixed groups: the single feature that splits each best (leave-one-out),\n"
          "#    fitted on all its rows. Check that it makes sense before it becomes a rule.\n")
        for g in cov["name_groups"] + cov["iban_groups"]:
            split = g.get("split")
            if not split:
                continue
            cats = ", ".join(f"{c} {k}" for c, k in g["truths"].most_common())
            w(f"# {g['id']} {g['key']} ({g['rows']} rows: {cats}; {_names(g['names'], 3)})\n")
            if split["best"]:
                w(f"#     {split['best']} {100 * split['features'][split['best']]:.0f}% vs top category "
                  f"{100 * split['majority']:.0f}%: {split['detail']}\n")
            else:
                w(f"#     nothing beats the top category ({100 * split['majority']:.0f}%)\n")

        w("\n# 3. Suggested roles for your own accounts (for the local accounts config):\n")
        for iban, r in sorted(cov["accounts"].items(), key=lambda kv: (kv[1]["role"], kv[0])):
            w(f"# {iban}  {r['role']:<8} ({r['rows']} rows; {_names(r['names'], 3)})\n")

        w(f"\n# 4. Account groups at >= {100 * READY_SHARE:.0f}% one category:\n")
        for g in cov["iban_groups"]:
            top = _top(g["truths"])
            share = g["truths"][top] / g["rows"]
            if share >= READY_SHARE:
                w(f"# {g['id']} {g['key']}: {top} {100 * share:.0f}% ({g['rows']} rows, {g['stability']}; "
                  f"{_names(g['names'], 3)})\n")
