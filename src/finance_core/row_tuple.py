"""
The canonical comparison form of a sheet row, and the two blocks (plan 4.5).

A row the bot is about to write and the same row read back from Sheets are not
naturally comparable: the first is ``["24-06-2026", 12.3, desc, cat]``, the
second comes back as a date serial and an int or float. Every comparison in
the Google layer (prefix digest, reconciliation, undo's content matching)
therefore compares ``RowTuple``s, and ``canonical`` is their only producer.

A RowTuple is a comparison form only. It carries no bank fields, so it can
never produce a ledger key, and it is never written to a sheet.
"""

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Tuple

RowTuple = Tuple[str, str, str, str]   # (ISO date, f"{amount:.2f}", description, category)

SHEETS_EPOCH = date(1899, 12, 30)
_DMY_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Block:
    name: str
    first_col: str
    last_col: str

    def a1(self, first_row: int, last_row=None) -> str:
        return f"{self.first_col}{first_row}:{self.last_col}{'' if last_row is None else last_row}"


EXPENSES = Block("expenses", "B", "E")
INCOME = Block("income", "G", "J")
BLOCKS = (EXPENSES, INCOME)
BLOCKS_BY_NAME = {b.name: b for b in BLOCKS}


def block_for(tx) -> Block:
    """CRDT rows go to the income block G:J, every other row to the expense block B:E."""
    return INCOME if tx.get("credit_debit_indicator") == "CRDT" else EXPENSES


def _text(v) -> str:
    try:
        return str(v).strip()
    except Exception:
        return ""


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def canonical_date(v) -> str:
    """Serial -> ISO, 'D-M-YYYY' -> ISO, ISO unchanged, anything else -> str(v).strip()."""
    try:
        if _is_number(v) and math.isfinite(v):
            return (SHEETS_EPOCH + timedelta(days=math.floor(v))).isoformat()
        s = _text(v)
        m = _DMY_RE.match(s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        return s
    except (ValueError, OverflowError):
        return _text(v)


def canonical_amount(v) -> str:
    """int/float or a numeric string -> f"{v:.2f}" with a '.' separator; else str(v).strip()."""
    try:
        if _is_number(v):
            x = float(v)
        else:
            x = float(_text(v))
        if not math.isfinite(x):
            return _text(v)
        x = round(x, 2)
        return f"{0.0 if x == 0 else x:.2f}"
    except (ValueError, OverflowError):
        return _text(v)


def canonical(row) -> RowTuple:
    """
    The only producer of a RowTuple. Total: never raises, whatever the cells hold.

    Not idempotent, so it is never applied to a RowTuple: read_block returns
    tuples that are already canonical.
    """
    cells = list(row or ())[:4]
    cells += [""] * (4 - len(cells))
    return (canonical_date(cells[0]), canonical_amount(cells[1]), _text(cells[2]), _text(cells[3]))


def is_iso(s: str) -> bool:
    return bool(_ISO_RE.match(s or ""))
