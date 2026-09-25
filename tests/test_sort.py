"""
Tests for sheet_writer.sort_by_date and compact_block (plan 4.5, revision 11's G1).

A sort touches rows the bot did not write, so it must write back the raw cell
values with RAW, never RowTuples through USER_ENTERED: under nl_NL '.' is the
thousands separator and a RowTuple amount "12.34" would be re-parsed.
"""

from datetime import date

from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.sheet_writer import commit_append, read_block, sort_by_date

from fakes import FakeSpreadsheet, FakeWorksheet, expense_tx, serial

NOT_APPENDING = lambda sheet_id: False  # noqa: E731


def sheet(rows=77):
    return FakeSpreadsheet(tabs=[FakeWorksheet("Transactions", rows=rows)])


def dated(day, amount, desc="x", cat="Boodschappen", month=6):
    return [serial(date(2026, month, day)), amount, desc, cat]


def test_sort_writes_raw_cells_with_raw_option():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [dated(20, 12.34, "b"), dated(3, 1234.5, "a")])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    update = ws.updates()[-1]
    assert update[2] == "RAW"
    first = update[3][0]
    assert isinstance(first[0], int)                 # a date serial, not an ISO string
    assert isinstance(first[1], (int, float))        # a number, not "1234.50"


def test_amount_is_identical_before_and_after_a_sort():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [dated(20, 12.34, "b"), dated(3, 1234.5, "a"), dated(9, 7, "c")])
    before = {r[2]: r[1] for r in ws.rows("B", "E")}
    sort_by_date(sh, is_appending=NOT_APPENDING)
    after = {r[2]: r[1] for r in ws.rows("B", "E")}
    assert before == after
    assert [r[2] for r in ws.rows("B", "E")] == ["a", "c", "b"]


def test_headers_are_untouched_and_data_starts_at_row_5():
    sh = sheet()
    ws = sh.transactions
    ws.put("B4", [["Date", "Amount", "Description", "Category"]])
    ws.put("B5", [dated(20, 1), dated(3, 2)])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert ws.get("B4:E4") == [["Date", "Amount", "Description", "Category"]]
    assert ws.updates()[-1][1].startswith("B5:")


def test_row_count_is_preserved():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [dated(d, d) for d in (9, 2, 30, 14, 1)])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert len(ws.rows("B", "E")) == 5


def test_blank_row_inside_the_block_is_compacted_with_no_stale_tail():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [dated(9, 1, "late"), ["", "", "", ""], dated(2, 2, "early"), dated(5, 3, "mid")])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert [r[2] for r in ws.rows("B", "E")] == ["early", "mid", "late"]
    assert all(ws.cells.get((8, c)) is None for c in range(2, 6))


def test_single_row_needs_no_write():
    sh = sheet()
    sh.transactions.put("B5", [dated(9, 1)])
    assert sort_by_date(sh, is_appending=NOT_APPENDING) == (1, 0)
    assert sh.transactions.updates() == []


def test_already_sorted_contiguous_block_is_not_rewritten():
    sh = sheet()
    sh.transactions.put("B5", [dated(1, 1), dated(2, 2)])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert sh.transactions.updates() == []


def test_income_and_expense_blocks_are_independent():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [dated(9, 1, "e2"), dated(2, 2, "e1"), dated(3, 3, "e1b")])
    ws.put("G5", [dated(1, 5, "i1"), dated(8, 6, "i2")])
    assert sort_by_date(sh, is_appending=NOT_APPENDING) == (3, 2)
    assert [r[2] for r in ws.rows("B", "E")] == ["e1", "e1b", "e2"]
    assert [r[2] for r in ws.rows("G", "J")] == ["i1", "i2"]
    assert all(u[1].startswith("B") for u in ws.updates())


def test_sort_is_stable_for_same_day_rows():
    sh = sheet()
    sh.transactions.put("B5", [dated(5, 1, "first"), dated(1, 1, "x"), dated(5, 1, "second")])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert [r[2] for r in sh.transactions.rows("B", "E")] == ["x", "first", "second"]


def test_text_typed_dates_sort_chronologically_and_stay_text():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [dated(20, 1, "serial"), ["03-06-2026", 2, "text", "Boodschappen"]])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    rows = ws.rows("B", "E")
    assert [r[2] for r in rows] == ["text", "serial"]
    assert rows[0][0] == "03-06-2026"               # RAW keeps the hand-typed text as it was


def test_an_amount_survives_the_user_entered_round_trip_under_nl_nl():
    sh = sheet()
    commit_append(sh, EXPENSES, [expense_tx(amount="-1234.56", seq="1")])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert read_block(sh, EXPENSES).tuples[0][1] == "1234.56"
    assert sh.transactions.rows("B", "E")[0][1] == 1234.56


def test_unparseable_dates_sort_last_in_their_original_order():
    sh = sheet()
    sh.transactions.put("B5", [["??", 1, "q1", "c"], dated(4, 1, "d"), ["", 1, "q2", "c"]])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert [r[2] for r in sh.transactions.rows("B", "E")] == ["d", "q1", "q2"]
    assert read_block(sh, INCOME).tuples == []
