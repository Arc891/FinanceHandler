"""
Tests for scripts/apply_rule_draft.py: the user's decision table
(rule-draft-N.txt from eval_categoriser --rules --draft-out) becomes the
local rules file the bot reads. The user changes only the first word of a
line; a line the change leaves without what its decision needs is refused
by group id, and nothing is written. What the script prints holds counts
and group ids only. The converted rules must decide every row as the draft
proposed it. All data is synthetic.
"""

import os
import re
import stat

import apply_rule_draft as ard
import rule_coverage as rc
from finance_core import categorization_rules as cr
from finance_core.local_rules import parse_local_rules
from test_rule_analysis import RECENT, coverage


def draft_text(tmp_path, edit=None):
    path = tmp_path / "draft.txt"
    rc.write_draft(coverage(RECENT), str(path))
    text = path.read_text()
    return edit(text) if edit else text


def first_word(text, key, word):
    """What the user does: change the first word of the line for `key`."""
    return re.sub(rf"^\w+(\t[^\t]*\t[^\t]*\t[^\t]*\t{re.escape(key)}\t)", rf"{word}\1", text, flags=re.M)


def test_the_converted_rules_decide_every_recent_row_as_the_draft_proposed(tmp_path):
    cov = coverage(RECENT)
    out = ard.convert(draft_text(tmp_path))
    assert out.errors == []
    local = parse_local_rules(out.text)
    active = [(d, re.compile(d["pattern"], re.I)) for d in cov["draft"] if d["decision"] != "drop"]
    checked = 0
    for t, _ in RECENT:
        d, m, y = t["booking_date"].split("-")
        if f"{m}/{y}" not in cov["window"] or cr.first_matching_rule(t, []) is not None:
            continue
        text, direction = cr.search_text(t), rc.tx_direction(t)
        draft = next((d for d, rx in active if d["direction"] == direction and rx.search(text)), None)
        want = draft["decide"](t) if draft else (None, False)
        got = cr.rule_result(t, local)
        assert ((got[0], got[2]) if got else (None, False)) == want
        checked += 1
    # 2025 rows no rule in constants.py covers: every group but the two Jumbo rows.
    assert checked == 53


def test_each_decision_becomes_its_rule_lines(tmp_path):
    rules = parse_local_rules(ard.convert(draft_text(tmp_path)).text)
    by = {}
    for r in rules:
        by.setdefault(r.description, []).append((r.category.value if r.category else "ai", r.marked))
    assert by["Buurtwinkel"] == [("Boodschappen", False)]
    assert by["Tuincentrum"] == [("Huishouden", True)]
    assert by["Kerk Het"] == [("Goeie doelen", True), ("Goeie doelen", False)]
    # A split: its branches, then a line that sends any other value to the AI.
    assert sorted(by["Sportschool"]) == [("Dates/uitjes", False), ("Rekeningen", False)]
    assert "Warenhuis" not in by and "Oude Slager" not in by


def test_a_dropped_group_the_user_turns_to_review_becomes_a_marked_rule(tmp_path):
    text = draft_text(tmp_path, lambda t: first_word(t, "warenhuis", "review"))
    rules = parse_local_rules(ard.convert(text).text)
    (shop,) = [r for r in rules if r.description == "Warenhuis"]
    assert shop.marked and shop.category.value == "Cadeautjes"


def test_a_split_the_user_turns_to_keep_is_refused_by_group_id(tmp_path):
    text = draft_text(tmp_path, lambda t: first_word(t, "sportschool", "keep"))
    out = ard.convert(text)
    assert len(out.errors) == 1 and out.errors[0].startswith("N")
    assert "category" in out.errors[0] and "sportschool" not in out.errors[0]


def test_an_unknown_first_word_is_refused(tmp_path):
    out = ard.convert(draft_text(tmp_path, lambda t: first_word(t, "buurtwinkel", "keeep")))
    assert len(out.errors) == 1 and "keeep" in out.errors[0]


def test_the_script_writes_a_private_file_and_prints_counts_only(tmp_path, capsys):
    draft = tmp_path / "draft.txt"
    draft.write_text(draft_text(tmp_path))
    target = tmp_path / "local_rules.tsv"
    assert ard.main([str(draft), str(target)]) == 0
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    printed = capsys.readouterr().out
    assert "keep 1" in printed and "split 2" in printed
    for secret in ("Buurtwinkel", "buurtwinkel", "Eigen", "150.00", "NL98"):
        assert secret not in printed


def test_nothing_is_written_when_a_line_is_refused(tmp_path):
    draft = tmp_path / "draft.txt"
    draft.write_text(draft_text(tmp_path, lambda t: first_word(t, "sportschool", "keep")))
    target = tmp_path / "local_rules.tsv"
    assert ard.main([str(draft), str(target)]) == 1
    assert not target.exists()


def test_a_cut_writes_the_category_from_the_amount_up_and_leaves_the_rest_to_the_ai(tmp_path):
    """N07: free money is the large transfers; smaller ones go to the AI."""
    text = draft_text(tmp_path, lambda t: first_word(t, "warenhuis", "cut=125"))
    out = ard.convert(text)
    assert out.errors == [] and out.counts["cut"] == 1
    local = parse_local_rules(out.text)
    shop = [r for r in local if r.description == "Warenhuis"]
    assert [(r.category.value, r.marked) for r in shop] == [("Cadeautjes", False)]
    big = tx_for("warenhuis", "125.00")
    small = tx_for("warenhuis", "124.99")
    assert cr.rule_result(big, local)[0] == "Cadeautjes"
    assert cr.rule_result(small, local) is None       # the `ai` line: the AI decides


def test_a_cut_on_a_split_line_without_a_category_is_refused(tmp_path):
    out = ard.convert(draft_text(tmp_path, lambda t: first_word(t, "eigen rekening", "cut=125")))
    assert len(out.errors) == 1 and "category" in out.errors[0] and "eigen" not in out.errors[0]


def test_a_cut_needs_a_positive_amount(tmp_path):
    for word in ("cut=", "cut=abc", "cut=-5", "cut=0"):
        out = ard.convert(draft_text(tmp_path, lambda t: first_word(t, "warenhuis", word)))
        assert len(out.errors) == 1 and "amount" in out.errors[0]


def tx_for(key, amount):
    """A new row for the group `key`, at `amount`."""
    from test_rule_analysis import tx
    name = next(t for t, _ in RECENT if rc.merchant_key(t) == key)["debtor"]["name"]
    return tx("20-12-2025", amount, name=name, rem="x")
