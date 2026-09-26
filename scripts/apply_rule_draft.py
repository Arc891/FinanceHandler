"""
Turn the rule draft's decisions into the local rules file the bot reads.

    python scripts/apply_rule_draft.py /tmp/eval/rule-draft-7.txt src/config/local_rules.tsv

The draft is what `eval_categoriser.py --rules --draft-out` wrote, with the
first word of each decision line changed where the user decided otherwise:

    keep    one plain rule
    review  one rule whose rows are marked for the user to check
    gd      Goeie doelen: card payments (BEA) marked, the rest plain
    cut=A   the category for amounts from A up, plain; smaller amounts go
            to the AI (an `ai` line)
    split   one rule per branch of the fitted split, then an `ai` line so a
            value the split never saw goes to the AI
    drop    no rule

A line whose decision it cannot carry out (a `keep` on a split line has no
category; an unknown first word) is refused by group id, and nothing is
written. The description is the group's key, capitalised; the rules file
(see finance_core/local_rules.py) can be edited afterwards. What this
prints holds counts and group ids only; the output file is 0600.
"""

import os
import re
import sys
from collections import Counter
from types import SimpleNamespace

DECISIONS = ("keep", "review", "gd", "split", "cut", "drop")
CUT = re.compile(r"^cut=(.*)$")
GOEIE_DOELEN = "Goeie doelen"
HEADER = ("# Local rules, from the rule draft by scripts/apply_rule_draft.py. PRIVATE: holds\n"
          "# names and amounts. Columns (tab-separated): direction, pattern, when, category,\n"
          "# mark (? or -), description, source. See src/finance_core/local_rules.py.\n")


def _branch_when(feature, describe, direction, word):
    """The condition for one branch of a split, or None for a branch no row can reach."""
    if describe in ("any", "all"):
        return "-"
    if feature == "direction":
        return "-" if describe == direction else None
    if feature == "code":
        return f"code={describe}"
    if feature == "weekend":
        return {"weekend": "weekend", "weekday": "weekday"}.get(describe)
    if feature in ("time of day", "amount"):
        field = "hour" if feature == "time of day" else "amount"
        if describe == "none":
            return "hour=none" if field == "hour" else None
        m = re.fullmatch(r"(below|from) (\d+(?:\.\d+)?)h?", describe)
        if not m:
            raise ValueError(f"cannot read a {feature} branch")
        return f"{field}{'<' if m[1] == 'below' else '>='}{m[2]}"
    if feature == "recurring amount":
        m = re.fullmatch(r"(not at|at) ([\d./]+)", describe)
        if not m:
            raise ValueError("cannot read a recurring amount branch")
        return f"amount{'!=' if m[1] == 'not at' else '='}{m[2]}"
    if feature == "keyword":
        m = re.fullmatch(r"with '([a-z]+)'", describe)
        if m:
            return f"word={m[1]}"
        if describe == "without" and word:
            return f"word!={word}"
        raise ValueError("cannot read a keyword branch")
    raise ValueError(f"cannot split on {feature!r}")


def _split_lines(direction, pattern, branches, description, source):
    feature, _, detail = branches.partition(": ")
    items = []
    for item in detail.split("; "):
        m = re.fullmatch(r"(.+) -> (.+) \(\d+\)", item)
        if not m:
            raise ValueError("cannot read the branches")
        items.append((m[1], m[2]))
    word = next((m[1] for d, _ in items if (m := re.fullmatch(r"with '([a-z]+)'", d))), None)
    lines = []
    for describe, outcome in items:
        when = _branch_when(feature, describe, direction, word)
        if when is not None and outcome != "ai":
            lines.append((direction, pattern, when, outcome, "-", description, source))
    lines.append((direction, pattern, "-", "ai", "-", "-", source))
    return lines


def _cut_amount(text):
    try:
        value = float(text)
    except ValueError:
        value = 0
    if not value > 0:
        raise ValueError("cut needs a positive amount, e.g. cut=125")
    return f"{value:g}"


def _decision(word):
    return "cut" if CUT.match(word) else word


def _lines(fields):
    decision, gid, direction, category, key, pattern, branches = fields[:7]
    amount = None
    if m := CUT.match(decision):
        decision, amount = "cut", _cut_amount(m[1])
    source = f"{gid} {direction}"
    description = key.title()
    if decision == "drop":
        return []
    if decision == "split":
        if " -> " not in branches:
            raise ValueError("split needs the branches of a fitted split")
        return _split_lines(direction, pattern, branches, description, source)
    if decision == "gd":
        if direction != "out":
            raise ValueError("gd is an expense decision")
        return [("out", pattern, "code=BEA", GOEIE_DOELEN, "?", description, source),
                ("out", pattern, "-", GOEIE_DOELEN, "-", description, source)]
    if category in ("", "-"):
        raise ValueError(f"{decision} needs a category (a split line has none; fill in the category column)")
    if decision == "cut":
        return [(direction, pattern, f"amount>={amount}", category, "-", description, source),
                (direction, pattern, "-", "ai", "-", "-", source)]
    return [(direction, pattern, "-", category, "?" if decision == "review" else "-", description, source)]


def convert(text):
    """SimpleNamespace(text, counts, errors): the rules file, decisions per kind, refusals by id."""
    out, counts, errors = [], Counter(), []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        gid = fields[1] if len(fields) > 1 else f"line {n}"
        where = f"{gid} {fields[2]}" if len(fields) > 2 else gid
        if len(fields) < 7:
            errors.append(f"{where}: too few columns")
            continue
        if _decision(fields[0]) not in DECISIONS:
            errors.append(f"{where}: unknown decision {fields[0]!r}")
            continue
        try:
            rules = _lines(fields)
        except ValueError as exc:
            errors.append(f"{where}: {exc}")
            continue
        counts[_decision(fields[0])] += 1
        out += rules
    body = "".join("\t".join(rule) + "\n" for rule in out)
    return SimpleNamespace(text=HEADER + body, counts=counts, rules=len(out), errors=errors)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    draft, target = args
    with open(draft, encoding="utf-8") as f:
        result = convert(f.read())
    for error in result.errors:
        print(f"refused: {error}")
    kinds = ", ".join(f"{k} {result.counts[k]}" for k in DECISIONS)
    if result.errors:
        print(f"nothing written: {len(result.errors)} line(s) refused ({kinds})")
        return 1
    # Validate what the bot will read before replacing anything.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    from finance_core.local_rules import LocalRulesError, parse_local_rules
    try:
        parse_local_rules(result.text)
    except LocalRulesError as exc:
        print(f"nothing written: the rules would not load ({exc})")
        return 1
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(result.text)
    print(f"{result.rules} rule lines written ({kinds})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
