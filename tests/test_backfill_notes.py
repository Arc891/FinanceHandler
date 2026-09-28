"""Historical note backfill uses only unambiguous multiset matches."""

from datetime import date
import csv
import pytest

import backfill_notes
from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.sheet_index import save_index
from finance_core.sheet_writer import read_block
from fakes import FakeSpreadsheet, make_transactions, serial


def row(day, amount, description, note, *, block="expenses", hints=()):
    return backfill_notes.ExportRow(block, f"2026-06-{day:02d}", f"{amount:.2f}", note, tuple(hints))


def sheet():
    return FakeSpreadsheet(tabs=[make_transactions()])


def test_csv_parse_keeps_raw_bank_text_and_rejects_bad_rows():
    good = ["24-06-2026", "", "NL00TEST", "Example Shop", "", "", "", "", "", "EUR",
            "-12.34", "", "", "", "", "1", "", "original payment text"]
    rows, invalid = backfill_notes.parse_export_rows([good, good[:10], [*good[:10], "not money", *good[11:]]])
    assert invalid == 2
    assert len(rows) == 1 and rows[0].block == "expenses"
    assert rows[0].date == "2026-06-24" and rows[0].amount == "12.34"
    assert "Example Shop" in rows[0].note and "original payment text" in rows[0].note


def test_unique_match_writes_only_empty_note_in_its_own_block():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [[serial(date(2026, 6, 24)), 12.34, "Short text", "Boodschappen"],
                  [serial(date(2026, 6, 25)), 3.0, "Other", "Boodschappen"]])
    ws.put("G5", [[serial(date(2026, 6, 24)), 12.34, "Income", "Salaris"]])
    ws.notes[(6, 4)] = "keep existing"
    items = [row(24, 12.34, "", "expense detail"),
             row(25, 3.0, "", "new detail"),
             row(24, 12.34, "", "income detail", block="income")]
    expenses = backfill_notes.plan_block(EXPENSES, read_block(sh, EXPENSES), ["", "keep existing"], items)
    income = backfill_notes.plan_block(INCOME, read_block(sh, INCOME), [""], items)
    assert expenses.changes == {"D5": "expense detail"}
    assert expenses.counts["occupied"] == 1
    assert income.changes == {"I5": "income detail"}


def test_duplicate_date_amount_with_distinct_notes_is_ambiguous_without_description():
    sh = sheet()
    sh.transactions.put("B5", [[serial(date(2026, 6, 24)), 12.34, "AI text", "X"],
                                    [serial(date(2026, 6, 24)), 12.34, "Other AI text", "X"]])
    items = [row(24, 12.34, "", "bank A"), row(24, 12.34, "", "bank B")]
    plan = backfill_notes.plan_block(EXPENSES, read_block(sh, EXPENSES), ["", ""], items)
    assert plan.changes == {} and plan.counts["ambiguous"] == 2


def test_duplicate_date_amount_uses_exact_bank_description_as_tiebreaker():
    sh = sheet()
    sh.transactions.put("B5", [[serial(date(2026, 6, 24)), 12.34, "Store B", "X"],
                                    [serial(date(2026, 6, 24)), 12.34, "Store A", "X"]])
    items = [row(24, 12.34, "", "bank A", hints=("Store A",)),
             row(24, 12.34, "", "bank B", hints=("Store B",))]
    plan = backfill_notes.plan_block(EXPENSES, read_block(sh, EXPENSES), ["", ""], items)
    assert plan.changes == {"D5": "bank B", "D6": "bank A"}


def test_count_mismatch_and_cross_month_key_are_skipped():
    sh = sheet()
    sh.transactions.put("B5", [[serial(date(2026, 6, 24)), 12.34, "A", "X"]])
    items = [row(24, 12.34, "", "A"), row(24, 12.34, "", "B")]
    contents = read_block(sh, EXPENSES)
    mismatch = backfill_notes.plan_block(EXPENSES, contents, [""], items)
    assert mismatch.changes == {} and mismatch.counts["ambiguous"] == 1
    excluded = {("expenses", "2026-06-24", "12.34")}
    repeated = backfill_notes.plan_block(EXPENSES, contents, [""], items[:1], excluded=excluded)
    assert repeated.changes == {} and repeated.counts["ambiguous"] == 1


def test_apply_rechecks_values_and_notes_before_writing():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [[serial(date(2026, 6, 24)), 12.34, "Short", "X"]])
    contents = read_block(sh, EXPENSES)
    plan = backfill_notes.plan_block(EXPENSES, contents, [""], [row(24, 12.34, "", "detail")])
    ws.notes[(5, 4)] = "new owner note"
    assert backfill_notes.apply_block(sh, EXPENSES, contents, plan) is False
    assert ws.notes[(5, 4)] == "new owner note"
    ws.notes.clear()
    ws.put("B5", [[serial(date(2026, 6, 25)), 12.34, "Short", "X"]])
    assert backfill_notes.apply_block(sh, EXPENSES, contents, plan) is False
    assert ws.notes == {}
    ws.put("B5", [[serial(date(2026, 6, 24)), 12.34, "Short", "X"]])
    assert backfill_notes.apply_block(sh, EXPENSES, contents, plan) is True
    assert ws.notes[(5, 4)] == "detail"


def test_apply_refuses_a_successful_response_that_did_not_store_the_note(monkeypatch):
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [[serial(date(2026, 6, 24)), 12.34, "Short", "X"]])
    contents = read_block(sh, EXPENSES)
    plan = backfill_notes.plan_block(EXPENSES, contents, [""], [row(24, 12.34, "", "detail")])
    monkeypatch.setattr(ws, "update_notes", lambda changes: None)
    with pytest.raises(RuntimeError, match="note readback"):
        backfill_notes.apply_block(sh, EXPENSES, contents, plan)


def test_live_style_dry_run_prints_counts_only_and_never_writes(tmp_path):
    name, remittance, account = "Private Name", "Private remittance", "NL00PRIVATE"
    export = tmp_path / "private.csv"
    bank_row = ["24-06-2026", "", account, name, "", "", "", "", "", "EUR",
                "-12.34", "", "", "", "", "1", "", remittance]
    with export.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(bank_row)
    sheets = {}
    index = {}
    for label in backfill_notes.MONTHS:
        sh = FakeSpreadsheet(sheet_id=f"private-{label}", title=f"Maandelijks Budget {label}",
                             tabs=[make_transactions()])
        sheets[sh.id] = sh
        index[label] = {"id": sh.id}
    sheets[index["06/2026"]["id"]].transactions.put("B5", [
        [serial(date(2026, 6, 24)), 12.34, "Short", "X"]])
    index_path = tmp_path / "index.json"
    save_index(index_path, index)

    class Workbooks:
        def open(self, sheet_id):
            return sheets[sheet_id]

    output = []
    result = backfill_notes.run(export, index_path, workbooks=Workbooks(), out=output.append)
    shown = "\n".join(output)
    assert result == 0 and "planned=1" in shown and "DRY RUN" in shown
    assert all(secret not in shown for secret in (name, remittance, account, "12.34", "private-"))
    assert all(not sh.transactions.notes for sh in sheets.values())


def test_live_style_run_refuses_wrong_sheet_title(tmp_path):
    export = tmp_path / "private.csv"
    with export.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(["24-06-2026", "", "NL00PRIVATE", "Private Name", "", "", "", "",
                                     "", "EUR", "-12.34", "", "", "", "", "1", "", "Private text"])
    index = {label: {"id": label} for label in backfill_notes.MONTHS}
    index_path = tmp_path / "index.json"
    save_index(index_path, index)

    class Workbooks:
        def open(self, sheet_id):
            return FakeSpreadsheet(sheet_id=sheet_id, title="Wrong month", tabs=[make_transactions()])

    output = []
    result = backfill_notes.run(export, index_path, apply=True, workbooks=Workbooks(), out=output.append)
    assert result == 1
    assert "wrong sheet title" in "\n".join(output)
    assert "Private" not in "\n".join(output)


def test_live_style_run_refuses_two_months_pointing_to_one_sheet(tmp_path):
    index = {label: {"id": "same-private-id"} for label in backfill_notes.MONTHS}
    index_path = tmp_path / "index.json"
    save_index(index_path, index)
    output = []
    result = backfill_notes.run(tmp_path / "unused.csv", index_path, out=output.append)
    assert result == 1 and "duplicate sheet registration" in "\n".join(output)
