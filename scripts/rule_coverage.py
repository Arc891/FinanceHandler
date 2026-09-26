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
- draft rules for the uniform groups, with their precision over every
  uncovered row, and suggested roles for the household's own accounts.

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

UIT_SPAARPOTJE = "Uit spaarpotje"
GOEIE_DOELEN = "Goeie doelen"
SPAARREKENING = "Spaarrekening"
VRIJ_GELD = "Persoonlijk vrij geld"

KEY_TOKEN = re.compile(r"[^\W_]+")      # letters and digits, accented ones too
TIME_OF_DAY = re.compile(r"(?<![\d:])([01]\d|2[0-3]):[0-5]\d(?![\d:])")
CODE_SHAPE = re.compile(r"^[A-Z]{2,4}$")
WORD = re.compile(r"[a-z]{3,}")


# ── reading a row ───────────────────────────────────────────────────────────

def _counterparty(tx):
    return ((tx.get("creditor") or {}).get("name") or
            (tx.get("debtor") or {}).get("name") or "").strip()


def _iban(tx):
    return (tx.get("counterparty_iban") or "").strip()


def _remittance(tx):
    return " ".join(tx.get("remittance_information") or [])


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


def _day(tx):
    from datetime import date
    from finance_core.row_tuple import canonical_date
    try:
        return date.fromisoformat(canonical_date(tx.get("booking_date", "")))
    except (TypeError, ValueError):
        return None


def tx_direction(tx):
    return "in" if tx.get("credit_debit_indicator") == "CRDT" else "out"


def tx_code(tx):
    """The bank's transaction code (BEA, IDB, ...), or `other` if not code-shaped."""
    parts = ((tx.get("bank_transaction_code") or {}).get("description") or "").split()
    return parts[-1] if parts and CODE_SHAPE.match(parts[-1]) else "other"


def tx_hour(tx):
    """The hour of a time of day in the remittance text (card payments), or None."""
    m = TIME_OF_DAY.search(_remittance(tx))
    return int(m.group(1)) if m else None


def tx_weekend(tx):
    day = _day(tx)
    return None if day is None else day.weekday() >= 5


def tx_year(tx):
    day = _day(tx)
    return None if day is None else day.year


def tx_amount(tx):
    try:
        return round(abs(float(tx["transaction_amount"]["amount"])), 2)
    except (KeyError, TypeError, ValueError):
        return None


def _cents(tx):
    amount = tx_amount(tx)
    return None if amount is None else round(amount * 100)


def tx_words(tx):
    return set(WORD.findall(_remittance(tx).lower()))


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


def _fit_majority(rows):
    top = _top(Counter(t for _, t in rows))
    return (lambda tx: top), f"always {top}"


def _fit_table(rows, value_of, describe):
    by = defaultdict(Counter)
    for tx, t in rows:
        by[value_of(tx)][t] += 1
    default = _top(Counter(t for _, t in rows))
    table = {v: _top(c) for v, c in by.items()}
    detail = "; ".join(f"{describe(v)} -> {table[v]} ({sum(by[v].values())})"
                       for v in sorted(by, key=str))
    return (lambda tx: table.get(value_of(tx), default)), detail


def _fit_threshold(rows, value_of, fmt):
    """One cut on a number; rows without the number are a branch of their own."""
    default = _top(Counter(t for _, t in rows))
    missing = Counter(t for tx, t in rows if value_of(tx) is None)
    if_missing = _top(missing) if missing else default
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
            best = (correct, (value + have[k + 1][0]) / 2, _top(below), _top(above))
    if best is None:
        return (lambda tx: if_missing if value_of(tx) is None else default), "no cut"
    _, cut, low, high = best

    def predict(tx):
        v = value_of(tx)
        return if_missing if v is None else (low if v < cut else high)
    return predict, f"below {fmt(cut)} -> {low}; from {fmt(cut)} -> {high}"


def _fit_recurring(rows):
    """Whether the amount is the group's most repeated one (a fixed transfer)."""
    amounts = Counter(tx_amount(tx) for tx, _ in rows if tx_amount(tx) is not None)
    repeated = [a for a, n in amounts.items() if n >= 2]
    if not repeated:
        return _fit_majority(rows)
    modal = min(repeated, key=lambda a: (-amounts[a], a))
    return _fit_table(rows, lambda tx: tx_amount(tx) == modal,
                      lambda v: f"{'at' if v else 'not at'} {modal:.2f}")


def _fit_keyword(rows, words_of):
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
            best = (correct, word, _top(present), _top(absent), present, absent)
    if best is None:
        return _fit_majority(rows)
    _, word, yes, no, present, absent = best
    detail = (f"with {word!r} -> {yes} ({sum(present.values())}); "
              f"without -> {no} ({sum(absent.values())})")
    return (lambda tx: yes if word in words_of(tx) else no), detail


def _features(words_of):
    """(name, fit) in order of preference when two score the same."""
    return (
        ("direction", lambda rows: _fit_table(rows, tx_direction, str)),
        ("code", lambda rows: _fit_table(rows, tx_code, str)),
        ("weekend", lambda rows: _fit_table(rows, tx_weekend,
                                            lambda v: {True: "weekend", False: "weekday"}.get(v, "no date"))),
        ("time of day", lambda rows: _fit_threshold(rows, tx_hour, lambda c: f"{c:.1f}h")),
        ("recurring amount", _fit_recurring),
        ("amount", lambda rows: _fit_threshold(rows, tx_amount, lambda c: f"{c:.2f}")),
        ("keyword", lambda rows: _fit_keyword(rows, words_of)),
        # Last, so any feature a rule could use wins a tie: a year split means
        # the booking habit changed, and the latest year is the one to follow.
        ("year", lambda rows: _fit_table(rows, tx_year, str)),
    )


def _leave_one_out(rows, fit):
    correct = 0
    for i, (tx, truth) in enumerate(rows):
        predict, _ = fit(rows[:i] + rows[i + 1:])
        correct += predict(tx) == truth
    return correct / len(rows)


def best_split(rows):
    """Which single feature predicts a group's category best, leave-one-out.

    The baseline is the top category's share, what a plain rule scores. It
    is not taken leave-one-out: in a balanced group that scores 0 (holding
    out a row hands the majority to the other category), which would make
    any split look like a gain. `detail` (the fitted split, which may hold
    an amount or a word) is for the private draft only.
    """
    words = {id(tx): tx_words(tx) for tx, _ in rows}
    features = _features(lambda tx: words[id(tx)])
    truths = Counter(t for _, t in rows)
    majority = truths[_top(truths)] / len(rows)
    scores = {name: _leave_one_out(rows, fit) for name, fit in features}
    top = max(scores.values())
    best = next(name for name, _ in features if scores[name] == top)
    if top - majority < USEFUL_GAIN:
        best = None
    detail = dict(features)[best](rows)[1] if best else ""
    return dict(majority=majority, features=scores, best=best, gain=top - majority, detail=detail)


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


def _propose(truths, share, stability, category):
    """keep (plain rule), review (top category, always marked) or gd (Goeie doelen)."""
    if truths[GOEIE_DOELEN] / sum(truths.values()) >= GD_SHARE:
        return "gd"
    if share >= KEEP_SHARE and stability != "shifts" and category == _top(truths):
        return "keep"
    return "review"


def _draft(uncovered, name_groups):
    """A proposed decision per name group and direction, tried on every uncovered row.

    A group that shifted between years follows its latest year. `hits` and
    `correct` count every uncovered row the pattern would catch.
    """
    from constants import ExpenseCategory, IncomeCategory
    from finance_core.categorization_rules import search_text
    drafts = []
    for g in name_groups:
        for direction in ("out", "in"):
            members = [(r, t) for r, t in g["members"] if tx_direction(r.tx) == direction]
            if len(members) < GROUP_MIN:
                continue
            truths = Counter(t for _, t in members)
            stability = _stability(members)
            category = _latest_top(members) if stability == "shifts" else _top(truths)
            share = truths[_top(truths)] / len(members)
            decision = _propose(truths, share, stability, category)
            if decision == "gd":
                category = GOEIE_DOELEN
            enum = IncomeCategory if direction == "in" else ExpenseCategory
            member = next((f"{enum.__name__}.{m.name}" for m in enum if m.value == category), None)
            if member is None:
                continue
            pattern = r"\b" + r"\W+".join(re.escape(w) for w in g["key"].split()) + r"\b"
            rx = re.compile(pattern, re.IGNORECASE)
            hits = [t for r, t in uncovered
                    if tx_direction(r.tx) == direction and rx.search(search_text(r.tx))]
            drafts.append(dict(id=g["id"], key=g["key"], direction=direction, decision=decision,
                               pattern=pattern, category=category, member=member, rows=len(members),
                               share=share, truths=truths, stability=stability, hits=len(hits),
                               correct=sum(t == category for t in hits), names=g["names"]))
    return drafts


def _watch(pairs, fired, rows, drafts):
    """Goeie doelen recall: donations the rules catch and the proposals would add."""
    caught = sum(1 for rule, row in zip(fired, rows)
                 if rule and row["correct"] and row["truth"] == GOEIE_DOELEN)
    proposed = [d for d in drafts if d["category"] == GOEIE_DOELEN]
    return dict(total=sum(1 for _, t in pairs if t == GOEIE_DOELEN), by_rules=caught,
                by_decisions=sum(d["truths"][GOEIE_DOELEN] for d in proposed),
                marked_other=sum(d["rows"] - d["truths"][GOEIE_DOELEN] for d in proposed))


def rule_coverage(records, truths, txs, spaarpot_names=()):
    """The regex pass alone, scored, plus what the uncovered rows have in common."""
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
    drafts = _draft(uncovered, name_groups)
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
        draft=drafts,
        watch=_watch(pairs, fired, rows, drafts),
    )


# ── the printed report: counts and names of things only ────────────────────

def _share(counter, n):
    return ", ".join(f"{_name(c)} {100 * k / n:.0f}%" for c, k in counter.most_common(3))


def _years(years):
    return ", ".join(f"{y} {ok}/{n}" for y, (n, ok) in sorted(years.items()))


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
        rows_by[x["decision"]] += x["rows"]
    keep = [x for x in d if x["decision"] == "keep"]
    lines.append("decisions proposed per name group (change the first word in the draft file): " +
                 ", ".join(f"{k} {kinds[k]} groups ({rows_by[k]} rows)" for k in ("keep", "review", "gd")) +
                 f"; keep rules hit {_pct(sum(x['hits'] for x in keep), sum(x['correct'] for x in keep))} "
                 "correct over all uncovered rows")
    for x in d:
        lines.append(f"  {x['id']} {x['direction']} {x['decision']}: {x['rows']} rows, top {100 * x['share']:.0f}%, "
                     f"{x['stability']}; hits {_pct(x['hits'], x['correct'])}")
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
          "#      review  this category, but always marked for you to check (multi-purpose shops)\n"
          "#      gd      Goeie doelen, catching too much rather than too little; rows that are\n"
          "#              less clearly a donation (e.g. a card payment) are marked\n"
          "#      drop    no rule; the AI decides\n"
          "#    You may also change the category. `hits` is over every row no rule covers today,\n"
          "#    so it shows what else the pattern would catch. Proposals: keep at >= "
          f"{100 * KEEP_SHARE:.0f}% one\n"
          f"#    category not shifting between years; gd at >= {100 * GD_SHARE:.0f}% donations; review otherwise\n"
          "#    (a group that shifted takes its latest year's category).\n")
        w("# decision\tid\tdirection\tcategory\tkey\tpattern\trows\ttop share\tstability\thits\tcategories\tnames\n")
        for d in cov["draft"]:
            cats = ", ".join(f"{c} {k}" for c, k in d["truths"].most_common())
            w(f"{d['decision']}\t{d['id']}\t{d['direction']}\t{d['category']}\t{d['key']}\t{d['pattern']}\t{d['rows']}\t"
              f"{100 * d['share']:.0f}%\t{d['stability']}\t{d['correct']}/{d['hits']}\t{cats}\t"
              f"{_names(d['names'], 3)}\n")

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
