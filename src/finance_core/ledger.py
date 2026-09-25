"""
Upload ledger and write audit (plan 4.6).

Two records with different licences, deliberately kept apart:

- the **dedup** record (``record_written``), written *before* a block is
  appended. It may over-record, never under-record: a spurious entry costs a
  skipped row, a missing one silently writes the row twice on the next
  overlapping upload.
- the **write audit** (``record_audit``), written *after* the append from
  exactly what landed. Undo is destructive and content-addressed, so the audit
  must never name a row that is not in the sheet.
"""

import hashlib
from decimal import Decimal, InvalidOperation

from finance_core.row_tuple import block_for, canonical_date


def _amount(tx) -> Decimal:
    raw = (tx.get("transaction_amount") or {}).get("amount", "0")
    try:
        return Decimal(str(raw).replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def counterparty(tx) -> str:
    return ((tx.get("debtor") or {}).get("name") or (tx.get("creditor") or {}).get("name") or "").strip()


def remittance_raw(tx) -> str:
    """The remittance as the bank wrote it, before csv_helper's normalisation."""
    if "remittance_raw" in tx:
        return (tx["remittance_raw"] or "").strip()
    rem = tx.get("remittance_information") or [""]
    return (rem[0] or "").strip()


def strong_key(tx) -> str:
    """sha1(booking_date | amount | counterparty | raw remittance | bank_sequence_no)."""
    parts = [
        (tx.get("booking_date") or "").strip(),
        f"{_amount(tx)}",
        counterparty(tx),
        remittance_raw(tx),
        (tx.get("bank_sequence_no") or "").strip(),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def weak_key(tx) -> str:
    """ISO date | abs(amount) | block: the only thing a row the old pipeline wrote still shares."""
    return weak_key_parts(canonical_date(tx.get("booking_date", "")), abs(_amount(tx)), block_for(tx).name)


def weak_key_parts(iso_date: str, abs_amount, block_name: str) -> str:
    return f"{iso_date}|{Decimal(str(abs_amount)).quantize(Decimal('0.01'))}|{block_name}"
