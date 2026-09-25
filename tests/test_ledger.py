"""
Tests for finance_core.ledger (plan 4.6): dedup record, write audit, filtering
and the intra-upload collapse.
"""

import json

from finance_core.ledger import Ledger, collapse_within_upload, strong_key, weak_key
from finance_core.row_tuple import canonical

from fakes import expense_tx, income_tx


def ledger(tmp_path):
    return Ledger(tmp_path / "upload_ledger.json")


def coffee(seq=""):
    return expense_tx(date_str="03-06-2026", amount="-2.50", name="Bakkerij", rem="koffie", seq=seq,
                      description="Koffie", category="Uit eten")


# ── keys ─────────────────────────────────────────────────────────────────────

def test_sequence_number_joins_the_strong_key():
    assert strong_key(coffee("1")) != strong_key(coffee("2"))
    assert strong_key(coffee("1")) == strong_key(coffee("1"))


def test_strong_key_ignores_ai_fields():
    a, b = coffee("1"), coffee("1")
    b["description"], b["category"] = "Something else", "Ander"
    assert strong_key(a) == strong_key(b)


def test_weak_key_is_iso_date_abs_amount_and_block():
    assert weak_key(coffee()) == "2026-06-03|2.50|expenses"
    assert weak_key(income_tx(date_str="24-06-2026", amount="314.1")) == "2026-06-24|314.10|income"


# ── multiset dedup ───────────────────────────────────────────────────────────

def test_identical_rows_are_both_written_then_neither_on_reupload(tmp_path):
    lg = ledger(tmp_path)
    txs = [coffee(), coffee()]                       # same key: no sequence number
    new, skipped = lg.filter_new(txs)
    assert len(new) == 2 and skipped == []
    lg.record_written("u1", "06/2026", new)
    new, skipped = lg.filter_new([coffee(), coffee()])
    assert new == [] and len(skipped) == 2
    assert all(s.reason == "strong" and s.label == "06/2026" for s in skipped)


def test_a_third_identical_row_is_new(tmp_path):
    lg = ledger(tmp_path)
    lg.record_written("u1", "06/2026", [coffee(), coffee()])
    new, skipped = lg.filter_new([coffee(), coffee(), coffee()])
    assert len(new) == 1 and len(skipped) == 2


def test_record_written_is_idempotent(tmp_path):
    lg = ledger(tmp_path)
    lg.record_written("u1", "06/2026", [coffee(), coffee()])
    lg.record_written("u1", "06/2026", [coffee(), coffee()])
    new, _ = lg.filter_new([coffee(), coffee(), coffee()])
    assert len(new) == 1


def test_strong_hit_in_any_label_is_skipped(tmp_path):
    lg = ledger(tmp_path)
    tx = coffee("7")
    lg.record_written("u1", "05/2026", [tx])
    new, skipped = lg.filter_new([tx])
    assert new == [] and skipped[0].label == "05/2026"


def test_weak_match_only_against_seeded_labels(tmp_path):
    lg = ledger(tmp_path)
    lg.seed_label("04/2026", [weak_key(coffee("9"))])
    new, skipped = lg.filter_new([coffee("9"), coffee("10")])
    assert len(new) == 1 and len(skipped) == 1
    assert skipped[0].reason == "weak" and skipped[0].label == "04/2026"


def test_weak_counts_are_consumed_with_multiplicity(tmp_path):
    lg = ledger(tmp_path)
    lg.seed_label("04/2026", [weak_key(coffee())] * 2)
    new, skipped = lg.filter_new([coffee("1"), coffee("2"), coffee("3")])
    assert len(new) == 1 and len(skipped) == 2


def test_bot_written_labels_are_not_weak_matched(tmp_path):
    lg = ledger(tmp_path)
    lg.record_written("u1", "07/2026", [coffee("1")])
    new, _ = lg.filter_new([coffee("2")])            # same date/amount/block, different transaction
    assert len(new) == 1


def test_skip_reports_the_label_it_was_found_in(tmp_path):
    # The pipeline compares this with the row's computed label to report the 04/05 seam.
    lg = ledger(tmp_path)
    lg.seed_label("04/2026", [weak_key(coffee())])
    _, skipped = lg.filter_new([coffee("1")])
    assert skipped[0].label == "04/2026"
    assert skipped[0].tx["bank_sequence_no"] == "1"


def test_no_pending_state_exists(tmp_path):
    lg = ledger(tmp_path)
    lg.record_written("u1", "06/2026", [coffee("1")])
    data = json.loads((tmp_path / "upload_ledger.json").read_text())
    assert set(data) == {"version", "strong", "seeded", "runs"}
    assert "pending" not in json.dumps(data)


# ── runs and the write audit ─────────────────────────────────────────────────

def test_run_carries_anchor_before(tmp_path):
    lg = ledger(tmp_path)
    anchor = {"anchor": {"boundary": "24-08-2026", "label": "09/2026"}, "history": [["24-07-2026", "08/2026"]]}
    lg.start_run("u1", anchor)
    lg.start_run("u1", {"something": "else"})          # idempotent: the first anchor wins
    assert lg.run("u1")["anchor_before"] == anchor


def test_audit_records_written_rows_as_content(tmp_path):
    lg = ledger(tmp_path)
    lg.start_run("u1", None)
    tx = coffee("1")
    pairs = [(strong_key(tx), canonical(["03-06-2026", 2.5, "Koffie", "Uit eten"]))]
    lg.record_audit("u1", "sheet-7", "expenses", pairs)
    assert lg.audited_rows("u1") == {"sheet-7": {"expenses": [pairs[0][1]]}}


def test_audit_is_a_multiset_max_union(tmp_path):
    # Reconcile re-audits found rows; that must not double what the first attempt audited.
    lg = ledger(tmp_path)
    lg.start_run("u1", None)
    t = canonical(["03-06-2026", 2.5, "Koffie", "Uit eten"])
    lg.record_audit("u1", "s", "expenses", [("k", t), ("k", t)])
    lg.record_audit("u1", "s", "expenses", [("k", t), ("k", t)])
    assert lg.audited_rows("u1")["s"]["expenses"] == [t, t]
    lg.record_audit("u1", "s", "expenses", [("k", t)] * 3)
    assert lg.audited_rows("u1")["s"]["expenses"] == [t, t, t]


def test_forget_run_drops_its_dedup_records_and_audit(tmp_path):
    lg = ledger(tmp_path)
    lg.start_run("u1", None)
    lg.record_written("u1", "06/2026", [coffee("1")])
    lg.record_written("u2", "06/2026", [coffee("2")])
    lg.record_audit("u1", "s", "expenses", [("k", ("a", "b", "c", "d"))])
    lg.forget_run("u1")
    new, skipped = lg.filter_new([coffee("1"), coffee("2")])
    assert [t["bank_sequence_no"] for t in new] == ["1"]
    assert lg.audited_rows("u1") == {}
    assert lg.run("u1")["undone_at"]


def test_ledger_survives_a_reload(tmp_path):
    ledger(tmp_path).record_written("u1", "06/2026", [coffee("1")])
    new, _ = ledger(tmp_path).filter_new([coffee("1")])
    assert new == []


# ── collapse_within_upload ───────────────────────────────────────────────────

def month(day0, days, seq0):
    return [expense_tx(date_str=f"{d:02d}-06-2026", amount=f"-{d}.00", seq=str(seq0 + d)) for d in range(day0, day0 + days)]


def test_overlapping_attachments_collapse_to_one_and_duplicate_pairs_stay_two():
    pair = [coffee(), coffee()]                        # a genuine same-day identical pair
    file_a = month(1, 20, 100) + pair
    file_b = month(11, 15, 100) + pair                 # overlaps days 11-20 and holds the same pair
    txs, collapsed = collapse_within_upload([file_a, file_b])
    keys = [strong_key(t) for t in txs]
    assert len(txs) == 25 + 2
    assert keys.count(strong_key(coffee())) == 2       # max across files, not the sum (4)
    assert collapsed == (22 + 17) - 27


def test_a_single_file_is_unchanged_by_the_collapse():
    f = month(1, 5, 0) + [coffee(), coffee()]
    txs, collapsed = collapse_within_upload([f])
    assert txs == f and collapsed == 0


def test_collapse_keeps_first_seen_order():
    a, b = month(1, 3, 0), month(2, 3, 0)
    txs, _ = collapse_within_upload([a, b])
    assert [t["booking_date"] for t in txs] == ["01-06-2026", "02-06-2026", "03-06-2026", "04-06-2026"]
