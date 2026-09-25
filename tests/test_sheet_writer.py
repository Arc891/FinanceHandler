"""
Tests for finance_core.sheet_writer and finance_core.row_tuple (plan 4.5).

The RowTuple round-trip against the real nl_NL workbook cannot be proved by a
fake written alongside the implementation; Phase 1's sandbox asserts it live.
"""

import json
import threading
from datetime import date

import pytest

from finance_core import sheet_writer
from finance_core.ledger import strong_key
from finance_core.row_tuple import EXPENSES, INCOME, block_for, canonical
from finance_core.sheet_writer import (AppendingError, commit_append, digest, plan_append,
                                       read_block, remove_rows, sort_by_date)

from fakes import FakeSpreadsheet, FakeWorksheet, expense_tx, income_tx, serial

NOT_APPENDING = lambda sheet_id: False  # noqa: E731


class Http503(Exception):
    def __init__(self):
        super().__init__("503 backend error")

        class R:
            status_code = 503
        self.response = R()


def sheet(rows=77):
    return FakeSpreadsheet(tabs=[FakeWorksheet("Transactions", rows=rows)])


def fill(ws, col, n, day0=date(2026, 6, 1), start=5, amount=1.0):
    """n contiguous pre-existing rows, as an old sheet would hold them."""
    ws.put(f"{col}{start}", [[serial(date(2026, 6, 1 + (i % 28))), amount + i, f"pre {i}", "Boodschappen"]
                             for i in range(n)])


# ── canonical ────────────────────────────────────────────────────────────────

def test_serial_text_and_iso_dates_canonicalise_identically():
    d = serial(date(2026, 1, 23))
    assert canonical([d, 1, "a", "b"])[0] == "2026-01-23"
    assert canonical(["23-01-2026", 1, "a", "b"])[0] == "2026-01-23"
    assert canonical(["2026-01-23", 1, "a", "b"])[0] == "2026-01-23"
    assert canonical([float(d), 1, "a", "b"])[0] == "2026-01-23"


def test_single_digit_text_date():
    assert canonical(["3-2-2026", 1, "", ""])[0] == "2026-02-03"


def test_int_and_float_amounts_canonicalise_identically():
    assert canonical(["", 12, "", ""])[1] == canonical(["", 12.0, "", ""])[1] == "12.00"
    assert canonical(["", 12.3, "", ""])[1] == "12.30"
    assert canonical(["", "12.30", "", ""])[1] == "12.30"
    assert canonical(["", -0.0, "", ""])[1] == "0.00"


def test_canonical_is_total_and_never_raises():
    weird = [object(), None, True, {"x": 1}, "€ 12,34", "31-02-2026", float("nan")]
    for v in weird:
        for slot in range(4):
            row = ["", "", "", ""]
            row[slot] = v
            t = canonical(row)
            assert len(t) == 4 and all(isinstance(x, str) for x in t)
    assert canonical(["31-02-2026", "€ 12,34", "  d ", " c"]) == ("31-02-2026", "€ 12,34", "d", "c")


def test_canonical_pads_short_rows():
    assert canonical([serial(date(2026, 6, 1))]) == ("2026-06-01", "", "", "")


def test_intended_row_equals_its_read_back_form():
    tx = expense_tx(date_str="24-06-2026", amount="-12.30")
    cells = sheet_writer.intended_cells(tx)
    written_back = [serial(date(2026, 6, 24)), 12.3, cells[2], cells[3]]
    assert canonical(cells) == canonical(written_back)


def test_block_assignment():
    assert block_for(income_tx()) is INCOME
    assert block_for(expense_tx()) is EXPENSES
    assert block_for({"credit_debit_indicator": "weird"}) is EXPENSES


# ── read_block / plan_append ─────────────────────────────────────────────────

def test_read_block_is_positional_with_explicit_blanks():
    sh = sheet()
    ws = sh.transactions
    fill(ws, "B", 2)
    ws.put("B8", [[serial(date(2026, 6, 9)), 5, "after gap", "Boodschappen"]])   # row 7 blank
    contents = read_block(sh, EXPENSES)
    assert len(contents.tuples) == 4
    assert contents.tuples[2] == ()
    assert contents.tuples[3][2] == "after gap"
    assert contents.last_row == 8
    assert contents.next_row == 9


def test_read_block_requests_unformatted_values():
    sh = sheet()
    fill(sh.transactions, "B", 1, amount=1234.5)
    contents = read_block(sh, EXPENSES)
    assert contents.tuples[0][1] == "1234.50"          # not "1.234,50"
    assert any(c[0] == "get" and c[2] == "UNFORMATTED_VALUE" for c in sh.transactions.calls)


def test_read_block_returns_raw_cells_alongside_tuples():
    sh = sheet()
    fill(sh.transactions, "G", 1, amount=7)
    contents = read_block(sh, INCOME)
    assert contents.cells[0][0] == serial(date(2026, 6, 1))
    assert contents.cells[0][1] == 7
    assert contents.tuples[0][:2] == ("2026-06-01", "7.00")


def test_empty_block_plans_from_row_5_with_empty_prefix():
    baseline = plan_append(sheet(), EXPENSES)
    assert baseline.first_write_row == 5
    assert baseline.prefix_digest == digest([])


def test_plan_append_records_first_write_row_and_prefix():
    sh = sheet(rows=196)
    fill(sh.transactions, "B", 99)       # the 05/2026 case: expenses resume at 104
    fill(sh.transactions, "G", 7)        # income at 12
    exp, inc = plan_append(sh, EXPENSES), plan_append(sh, INCOME)
    assert (exp.first_write_row, inc.first_write_row) == (104, 12)
    assert exp.prefix_digest == digest(read_block(sh, EXPENSES).tuples)
    assert not any(c[0] == "update" for c in sh.transactions.calls)


def test_plan_append_is_stable_over_text_typed_dates():
    # Modelled on 02/2026: 70 date cells stored as DD-MM-YYYY text among serials.
    sh = sheet(rows=200)
    ws = sh.transactions
    rows = []
    for i in range(104):
        d = date(2026, 1, 23 + i % 8)
        rows.append([f"{d.day:02d}-{d.month:02d}-{d.year}" if i < 69 else serial(d), 3 + i, "x", "y"])
    ws.put("B5", rows)
    first, second = plan_append(sh, EXPENSES), plan_append(sh, EXPENSES)
    assert first == second
    assert first.first_write_row == 109


def test_baseline_round_trips_through_json():
    b = plan_append(sheet(), EXPENSES)
    assert sheet_writer.BlockBaseline.from_dict(json.loads(json.dumps(b.to_dict()))) == b


# ── commit_append ────────────────────────────────────────────────────────────

def test_commit_append_writes_after_the_last_row_and_returns_audit_pairs():
    sh = sheet()
    fill(sh.transactions, "B", 3)
    txs = [expense_tx(seq="10"), expense_tx(date_str="25-06-2026", seq="11")]
    pairs = commit_append(sh, EXPENSES, txs)
    update = sh.transactions.updates()[-1]
    assert update[1] == "B8:E9"
    assert update[2] == "USER_ENTERED"
    assert [k for k, _ in pairs] == [strong_key(t) for t in txs]
    assert [t for _, t in pairs] == read_block(sh, EXPENSES).tuples[3:]


def test_commit_append_recomputes_its_append_point():
    sh = sheet()
    fill(sh.transactions, "B", 3)
    baseline = plan_append(sh, EXPENSES)
    fill(sh.transactions, "B", 5)                 # the block moved after planning
    commit_append(sh, EXPENSES, [expense_tx()])
    assert baseline.first_write_row == 8
    assert sh.transactions.updates()[-1][1] == "B10:E10"
    assert len([t for t in read_block(sh, EXPENSES).tuples if t]) == 6


def test_empty_sheet_starts_at_row_5():
    sh = sheet()
    commit_append(sh, INCOME, [income_tx()])
    assert sh.transactions.updates()[-1][1] == "G5:J5"


def test_blocks_are_independent():
    sh = sheet()
    fill(sh.transactions, "B", 10)
    commit_append(sh, INCOME, [income_tx()])
    assert sh.transactions.updates()[-1][1] == "G5:J5"
    assert len(read_block(sh, EXPENSES).tuples) == 10


def test_capacity_is_expanded_before_the_write():
    sh = sheet(rows=10)
    fill(sh.transactions, "B", 5)                 # rows 5..9
    commit_append(sh, EXPENSES, [expense_tx(seq=str(i)) for i in range(4)])   # needs row 13
    calls = sh.transactions.calls
    resize = next(i for i, c in enumerate(calls) if c[0] == "resize")
    update = next(i for i, c in enumerate(calls) if c[0] == "update")
    assert resize < update
    assert calls[resize][1] == 13 + 50


def test_no_sort_inside_append():
    sh = sheet()
    commit_append(sh, EXPENSES, [expense_tx(date_str="30-06-2026", seq="1"),
                                 expense_tx(date_str="01-06-2026", seq="2")])
    assert [t[0] for t in read_block(sh, EXPENSES).tuples] == ["2026-06-30", "2026-06-01"]
    assert len(sh.transactions.updates()) == 1


def test_write_that_lands_then_raises_is_not_retried():
    sh = sheet()
    sh.transactions.update_faults = [("after", Http503())]
    with pytest.raises(Http503):
        commit_append(sh, EXPENSES, [expense_tx()])
    assert len(sh.transactions.updates()) == 1
    assert len([t for t in read_block(sh, EXPENSES).tuples if t]) == 1     # present exactly once


def test_failure_is_logged_with_label_and_upload_id(tmp_path):
    sh = sheet()
    sh.transactions.update_faults = [("before", Http503())]
    log = tmp_path / "failed_uploads.json"
    with pytest.raises(Http503):
        commit_append(sh, EXPENSES, [expense_tx()], context={"upload_id": "u1", "period_label": "07/2026"},
                      failed_path=log)
    entry = json.loads(log.read_text())["failed"][0]
    assert entry["upload_id"] == "u1"
    assert entry["period_label"] == "07/2026"
    assert entry["spreadsheet_id"] == sh.id
    assert entry["block"] == "expenses"
    assert len(entry["transactions"]) == 1


def test_failure_log_keeps_existing_entries(tmp_path):
    log = tmp_path / "failed_uploads.json"
    log.write_text(json.dumps({"failed": [{"old": True}]}))
    sh = sheet()
    sh.transactions.update_faults = [("before", Http503())]
    with pytest.raises(Http503):
        commit_append(sh, EXPENSES, [expense_tx()], failed_path=log)
    assert len(json.loads(log.read_text())["failed"]) == 2


def test_concurrent_appends_to_one_sheet_do_not_overlap():
    sh = sheet(rows=200)
    sh.transactions.get_delay = 0.02          # widen the read-then-write window
    errors = []

    def worker(n):
        try:
            commit_append(sh, EXPENSES, [expense_tx(seq=f"{n}-{i}", description=f"w{n}-{i}") for i in range(3)])
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    descriptions = [t[2] for t in read_block(sh, EXPENSES).tuples]
    assert len(descriptions) == 12 and len(set(descriptions)) == 12


def test_empty_commit_writes_nothing():
    sh = sheet()
    assert commit_append(sh, EXPENSES, []) == []
    assert sh.transactions.updates() == []


# ── remove_rows ──────────────────────────────────────────────────────────────

def test_remove_rows_skips_what_it_cannot_find_and_compacts():
    sh = sheet()
    fill(sh.transactions, "B", 4)
    present = read_block(sh, EXPENSES).tuples
    ghost = ("2030-01-01", "1.00", "never", "written")
    removed, not_found = remove_rows(sh, EXPENSES, [present[1], ghost], is_appending=NOT_APPENDING)
    assert (removed, not_found) == (1, 1)
    after = read_block(sh, EXPENSES).tuples
    assert after == [present[0], present[2], present[3]]


def test_remove_rows_respects_multiplicity():
    sh = sheet()
    row = [serial(date(2026, 6, 3)), 2.5, "koffie", "Uit eten"]
    sh.transactions.put("B5", [row, row, row])
    t = canonical(row)
    assert remove_rows(sh, EXPENSES, [t, t], is_appending=NOT_APPENDING) == (2, 0)
    assert read_block(sh, EXPENSES).tuples == [t]


def test_remove_rows_refuses_while_the_sheet_is_appending():
    sh = sheet()
    fill(sh.transactions, "B", 2)
    with pytest.raises(AppendingError):
        remove_rows(sh, EXPENSES, [("2030-01-01", "1.00", "x", "y")], is_appending=lambda sid: sid == sh.id)
    assert sh.transactions.updates() == []


def test_sort_refuses_while_the_sheet_is_appending():
    sh = sheet()
    fill(sh.transactions, "B", 2)
    with pytest.raises(AppendingError):
        sort_by_date(sh, is_appending=lambda sid: True)
    assert sh.transactions.updates() == []


def test_compact_block_itself_carries_the_guard():
    sh = sheet()
    with pytest.raises(AppendingError):
        sheet_writer.compact_block(sh, EXPENSES, [], is_appending=lambda sid: True, previous_last_row=10)


@pytest.mark.parametrize("text", ["24-06-2026", "12,50", "'quoted", "=SUM(A1)"])
def test_descriptions_are_written_as_text_whatever_they_look_like(text):
    # Live sandbox 2026-09-25: USER_ENTERED turned the description "2-3" into a date
    # serial, so its RowTuple never matched again and undo left the row behind.
    sh = sheet()
    pairs = commit_append(sh, EXPENSES, [expense_tx(description=text, category=text)])
    back = read_block(sh, EXPENSES).tuples[-1]
    assert back[2:] == (text, text)
    assert pairs[0][1] == back
    assert remove_rows(sh, EXPENSES, [pairs[0][1]], is_appending=NOT_APPENDING) == (1, 0)
