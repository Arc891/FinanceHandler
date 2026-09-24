"""Synthetic ASN export rows for tests. No real data."""

import csv


def asn_row(date="24-04-2026", counterparty="Picnic", amount="-12.50",
            seq="979142", remittance="Boodschappen"):
    """A synthetic 20-column ASN export row."""
    row = [""] * 20
    row[0] = date
    row[1] = "NL00TEST0000000001"
    row[3] = counterparty
    row[7] = "EUR"
    row[9] = "EUR"
    row[10] = amount
    row[11] = date
    row[12] = date
    row[13] = "8810"
    row[14] = "IDB"
    row[15] = seq
    row[17] = remittance
    row[19] = "Boodschappen"
    return row


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return str(path)
