"""
Tests for csv_helper: row guards and the bank sequence number.

Phase 0 of docs/plans/MULTI_MONTH_UPLOAD_PLAN.md. Multi-file and attachment
tests join this module in Phase 3.
"""

import pytest

from config.spaarpot_uuid_map import SPAARPOT_UUID_MAP
from finance_core.csv_helper import load_transactions_from_csv, normalize_csv_data

from csv_rows import asn_row, write_csv


def test_sequence_number_is_carried(tmp_path):
    path = write_csv(tmp_path / "export.csv", [
        asn_row(seq="979142"),
        asn_row(date="25-04-2026", seq="979143"),
    ])
    txs = load_transactions_from_csv(path)
    assert [t["bank_sequence_no"] for t in txs] == ["979142", "979143"]


def test_missing_sequence_number_is_empty_string(tmp_path):
    path = write_csv(tmp_path / "export.csv", [asn_row(seq="")])
    assert load_transactions_from_csv(path)[0]["bank_sequence_no"] == ""


def test_short_row_does_not_break_normalisation(tmp_path):
    short = ["24-04-2026", "NL00TEST0000000001", "", "Picnic", "", "", "",
             "EUR", "", "EUR", "-1.00"]  # 11 columns, no remittance
    path = write_csv(tmp_path / "export.csv", [asn_row(), short, asn_row(seq="2")])
    normalize_csv_data(path)  # used to raise IndexError on row[17]


def test_short_row_is_skipped_and_the_rest_loaded(tmp_path):
    short = ["24-04-2026", "NL00TEST0000000001", "", "Picnic"]
    path = write_csv(tmp_path / "export.csv", [asn_row(seq="1"), short, asn_row(seq="2")])
    txs = load_transactions_from_csv(path)
    assert [t["bank_sequence_no"] for t in txs] == ["1", "2"]


def test_empty_lines_are_tolerated(tmp_path):
    path = tmp_path / "export.csv"
    write_csv(path, [asn_row(seq="1")])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n")
    assert len(load_transactions_from_csv(str(path))) == 1


@pytest.mark.skipif(not SPAARPOT_UUID_MAP, reason="no spaarpot mapping configured")
def test_spaarpot_reference_is_still_mapped(tmp_path):
    uuid, name = next(iter(SPAARPOT_UUID_MAP.items()))
    path = write_csv(tmp_path / "export.csv", [
        asn_row(counterparty="", remittance=f"Spaarpot Referentie: {uuid}"),
    ])
    rem = load_transactions_from_csv(path)[0]["remittance_information"][0]
    assert uuid not in rem
    assert f"- {name}" in rem


def test_existing_fields_unchanged(tmp_path):
    path = write_csv(tmp_path / "export.csv", [asn_row(amount="-12,50")])
    tx = load_transactions_from_csv(path)[0]
    assert tx["booking_date"] == "24-04-2026"
    assert tx["transaction_amount"] == {"amount": "-12.50", "currency": "EUR"}
    assert tx["credit_debit_indicator"] == "DBIT"
    assert tx["debtor"] == {"name": "Picnic"}
    assert tx["bank_transaction_code"] == {"description": "8810 IDB"}
