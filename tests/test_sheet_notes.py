"""
Tests for the bank note on each written row, and for compaction keeping
notes and number formats with their rows.

A row's description is often a short rule or AI text ("? Stichting ..."), too
little to check its category against. So every appended row gets a note on its
description cell with the bank's own text: counterparty, account and
remittance, plus the AI's unused guess for a flagged row. A sort or an undo
rewrites values, which never moves a note, so compaction rewrites the notes in
the new order; and it empties cells with a clear, because a RAW "" write strips
the number format (07-10/2026 lost the currency format of their first row).
"""

import logging
from datetime import date

from finance_core.flagging import apply_category
from finance_core.row_tuple import EXPENSES, INCOME, canonical
from finance_core.sheet_writer import bank_note, commit_append, remove_rows, sort_by_date

from fakes import FakeSpreadsheet, expense_tx, income_tx, make_transactions, serial

NOT_APPENDING = lambda sheet_id: False  # noqa: E731
D, I, C = 4, 9, 3                        # description columns of the two blocks, expense amount


def sheet():
    return FakeSpreadsheet(tabs=[make_transactions()])


def banked(tx, iban="NL00TEST0123456789"):
    return dict(tx, counterparty_iban=iban)


def test_bank_note_holds_counterparty_account_and_remittance():
    note = bank_note(banked(expense_tx(name="Stichting Voorbeeld", rem="gift juni")))
    assert note == ("Tegenpartij: Stichting Voorbeeld\n"
                    "Rekening: NL00TEST0123456789\n"
                    "Omschrijving: gift juni")


def test_bank_note_skips_missing_parts_and_is_empty_without_any():
    assert bank_note(expense_tx(name="Picnic", rem="")) == "Tegenpartij: Picnic"
    assert bank_note(expense_tx(name="", rem="")) == ""


def test_a_flagged_rows_note_carries_the_unused_ai_guess():
    class Result:
        method, category, confidence, description, description_suffix, marked = (
            "ai_low", "Boodschappen", 0.62, "Albert Heijn", None, False)
    row, guess = apply_category(expense_tx(name="AH 1234", rem="pinnen"), Result())
    assert guess and row["category"] == "! Nog in te delen !"
    assert bank_note(row).endswith("\nAI-suggestie: Boodschappen (0,62)")


def test_append_puts_the_note_on_each_description_cell():
    sh = sheet()
    txs = [banked(expense_tx("24-06-2026", "-5.00", "Picnic", "order 1", seq="1")),
           banked(expense_tx("25-06-2026", "-7.00", "Jumbo", "bon 2", seq="2"))]
    commit_append(sh, EXPENSES, txs)
    commit_append(sh, INCOME, [banked(income_tx("24-06-2026", "100.00", "DUO", "studiefinanciering"))])
    notes = sh.transactions.notes
    assert notes[(5, D)].startswith("Tegenpartij: Picnic") and "order 1" in notes[(5, D)]
    assert notes[(6, D)].startswith("Tegenpartij: Jumbo")
    assert notes[(5, I)].startswith("Tegenpartij: DUO")


def test_a_failed_note_write_does_not_fail_the_append(caplog):
    sh = sheet()
    sh.transactions.note_faults = [RuntimeError("quota Tegenpartij secret")] * 5
    tx = banked(expense_tx(name="Picnic", rem="order 1"))
    with caplog.at_level(logging.WARNING):
        pairs = commit_append(sh, EXPENSES, [tx])
    assert len(pairs) == 1 and sh.transactions.rows("B", "E")          # the row landed
    assert sh.transactions.notes == {}
    assert "note" in caplog.text.lower() and "secret" not in caplog.text and "Picnic" not in caplog.text


def test_sort_moves_each_note_with_its_row():
    sh = sheet()
    ws = sh.transactions
    ws.put("B5", [[serial(date(2026, 6, 20)), 2.0, "late", "Boodschappen"],
                  [serial(date(2026, 6, 3)), 1.0, "early", "Boodschappen"]])
    ws.notes = {(5, D): "note late", (6, D): "note early"}
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert ws.rows("D", "D") == [["early"], ["late"]]
    assert ws.notes == {(5, D): "note early", (6, D): "note late"}


def test_undo_drops_the_removed_rows_note_and_shifts_the_rest():
    sh = sheet()
    ws = sh.transactions
    rows = [[serial(date(2026, 6, d)), float(d), f"r{d}", "Boodschappen"] for d in (1, 2, 3)]
    ws.put("B5", rows)
    ws.notes = {(5, D): "n1", (6, D): "n2", (7, D): "n3"}
    removed, _ = remove_rows(sh, EXPENSES, [canonical(rows[0])], is_appending=NOT_APPENDING)
    assert removed == 1
    assert ws.notes == {(5, D): "n2", (6, D): "n3"}


def test_compaction_keeps_the_number_format_of_the_emptied_tail():
    sh = sheet()
    ws = sh.transactions
    rows = [[serial(date(2026, 6, d)), float(d), f"r{d}", "Boodschappen"] for d in (1, 2, 3)]
    ws.put("B5", rows)
    remove_rows(sh, EXPENSES, [canonical(rows[0])], is_appending=NOT_APPENDING)
    assert ws.rows("B", "E") == [r for r in rows[1:]]
    assert ws.formats[(7, C)] == "CURRENCY"                 # row 7 was emptied, not blanked
    assert not [c for c in ws.updates() if any(v == "" for row in c[3] for v in row)]
