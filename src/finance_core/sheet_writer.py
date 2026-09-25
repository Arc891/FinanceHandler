"""
Append, read, compact, sort and remove rows in a month's Transactions tab (plan 4.5).

Replaces the row-position machinery of background_upload.py: the next free row
is always read from the sheet, never remembered.

A block is one of the two four-column regions (expenses B:E, income G:J) whose
data starts at GSHEET_DATA_START_ROW. The writer only appends and compacts; it
never inserts and never writes above the start row.

Two row representations, never to be confused:
- RowTuples (row_tuple.canonical) for every comparison and the sort key;
- raw unformatted cells (date serials, int/float amounts) for writing back.
  compact_block writes those with RAW, because a RowTuple amount "12.34" sent
  USER_ENTERED to an nl_NL workbook would be re-parsed ('.' is the thousands
  separator there).

``commit_append`` is never retried: a values update is not idempotent, so a
failed write is reconciled from the recorded baseline (plan 4.6), never
repeated blind.
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, List, Tuple

from gspread.utils import ValueInputOption, ValueRenderOption

from finance_core.config_access import project_path, setting
from finance_core.google_retry import with_retry
from finance_core.google_sheets import format_transaction_for_sheet
from finance_core.ledger import strong_key
from finance_core.row_tuple import BLOCKS, EXPENSES, INCOME, Block, canonical, is_iso  # noqa: F401

logger = logging.getLogger(__name__)

TRANSACTIONS_TAB = "Transactions"
CAPACITY_BUFFER = 50
DEFAULT_FAILED_PATH = "data/failed_uploads.json"

IsAppending = Callable[[str], bool]


class AppendingError(RuntimeError):
    """Refused: a period writing to this spreadsheet is still `appending` (plan 4.6)."""


def data_start_row() -> int:
    return int(setting("GSHEET_DATA_START_ROW", 5))


# ── per-spreadsheet lock ─────────────────────────────────────────────────────

_locks = defaultdict(threading.RLock)
_locks_guard = threading.Lock()


def _lock(spreadsheet_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks[spreadsheet_id]


# ── reading ──────────────────────────────────────────────────────────────────

def _is_blank_cell(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _pad(row) -> list:
    cells = list(row or ())[:4]
    return cells + [""] * (4 - len(cells))


@dataclass(frozen=True)
class BlockContents:
    """One entry per sheet row from ``start`` to the last non-empty row; index i is row start + i."""
    start: int
    tuples: List[tuple]     # RowTuple, or () for an internal blank row
    cells: List[list]       # raw unformatted values, padded to four

    @property
    def last_row(self) -> int:
        return self.start + len(self.tuples) - 1

    @property
    def next_row(self) -> int:
        return self.start + len(self.tuples)


@dataclass(frozen=True)
class BlockBaseline:
    """Recorded per block before any write. ``first_write_row`` is an identity boundary, never a write position."""
    first_write_row: int
    prefix_digest: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BlockBaseline":
        return cls(int(d["first_write_row"]), str(d["prefix_digest"]))


def digest(tuples) -> str:
    """SHA-1 of a positional RowTuple sequence (blank rows included as empty lists)."""
    payload = json.dumps([list(t) for t in tuples], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def transactions_tab(spreadsheet):
    return with_retry(lambda: spreadsheet.worksheet(TRANSACTIONS_TAB), what="open Transactions tab")


def read_block(spreadsheet, block: Block, *, worksheet=None) -> BlockContents:
    """Read a block positionally, UNFORMATTED, returning RowTuples and raw cells side by side."""
    ws = worksheet or transactions_tab(spreadsheet)
    start = data_start_row()
    values = with_retry(
        lambda: ws.get(block.a1(start), value_render_option=ValueRenderOption.unformatted),
        what=f"read {block.name}")
    cells = [_pad(r) for r in values]
    while cells and all(_is_blank_cell(v) for v in cells[-1]):
        cells.pop()
    tuples = [() if all(_is_blank_cell(v) for v in c) else canonical(c) for c in cells]
    return BlockContents(start, tuples, cells)


def plan_append(spreadsheet, block: Block) -> BlockBaseline:
    """The baseline 4.6 persists before a write: first_write_row and the prefix digest."""
    contents = read_block(spreadsheet, block)
    return BlockBaseline(contents.next_row, digest(contents.tuples))


# ── appending ────────────────────────────────────────────────────────────────

def intended_cells(tx) -> list:
    """The four cells a transaction is written as (USER_ENTERED)."""
    return format_transaction_for_sheet(tx)


def ensure_capacity(worksheet, last_row: int) -> None:
    if last_row > worksheet.row_count:
        new_rows = last_row + CAPACITY_BUFFER
        logger.info("Expanding %s from %d to %d rows", worksheet.title, worksheet.row_count, new_rows)
        worksheet.resize(rows=new_rows)


def commit_append(spreadsheet, block: Block, txs, *, context=None, failed_path=None) -> List[Tuple[str, tuple]]:
    """
    Append ``txs`` after the block's current last row with ONE values update.

    Takes no baseline: the append point is recomputed here, immediately before
    the write, so a block that moved since plan_append is appended to, never
    overwritten. Does not sort. Returns the (ledger key, RowTuple) pairs written,
    the input to ledger.record_audit.
    """
    if not txs:
        return []
    cells = [intended_cells(tx) for tx in txs]
    pairs = [(strong_key(tx), canonical(c)) for tx, c in zip(txs, cells)]
    with _lock(spreadsheet.id):
        try:
            ws = transactions_tab(spreadsheet)
            first = read_block(spreadsheet, block, worksheet=ws).next_row
            last = first + len(cells) - 1
            ensure_capacity(ws, last)
            ws.update(values=cells, range_name=block.a1(first, last),
                      value_input_option=ValueInputOption.user_entered)
        except Exception as exc:
            _log_failure(spreadsheet, block, txs, exc, context or {}, failed_path)
            raise
    logger.info("Appended %d %s rows to %s", len(cells), block.name, spreadsheet.id)
    return pairs


def _log_failure(spreadsheet, block, txs, exc, context, failed_path) -> None:
    path = failed_path or project_path(setting("FAILED_UPLOADS_PATH", DEFAULT_FAILED_PATH))
    try:
        data = {"failed": []}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh) or {"failed": []}
        data.setdefault("failed", []).append({
            "upload_id": context.get("upload_id"),
            "period_label": context.get("period_label"),
            "spreadsheet_id": spreadsheet.id,
            "block": block.name,
            "error": f"{type(exc).__name__}: {exc}",
            "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "transactions": list(txs),
        })
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".failed.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:  # never mask the write error with a logging error
        logger.exception("Could not record the failed write in %s", path)


# ── compacting: sort and remove ──────────────────────────────────────────────

def _refuse_if_appending(spreadsheet, is_appending: IsAppending) -> None:
    if is_appending(spreadsheet.id):
        raise AppendingError(
            f"spreadsheet {spreadsheet.id} has a period still `appending`: run /resume first "
            "to reconcile it; only then sort or undo")


def compact_block(spreadsheet, block: Block, cells, *, is_appending: IsAppending,
                  previous_last_row: int, worksheet=None) -> None:
    """
    Rewrite the block from the start row with ``cells`` (raw values, RAW) and
    blank the tail down to ``previous_last_row``.

    Refuses for a spreadsheet with a period at `appending`: compaction shifts
    rows and would invalidate that period's positional baseline. The guard is
    here so every compacting caller (sort_by_date, remove_rows) inherits it.
    """
    _refuse_if_appending(spreadsheet, is_appending)
    start = data_start_row()
    rows = [_pad(c) for c in cells]
    end = max(previous_last_row, start + len(rows) - 1)
    if end < start:
        return
    payload = rows + [["", "", "", ""] for _ in range(end - start + 1 - len(rows))]
    with _lock(spreadsheet.id):
        ws = worksheet or transactions_tab(spreadsheet)
        ws.update(values=payload, range_name=block.a1(start, end),
                  value_input_option=ValueInputOption.raw)


def _date_key(t) -> tuple:
    return (0, t[0]) if is_iso(t[0]) else (1, "")


def sort_by_date(spreadsheet, *, is_appending: IsAppending) -> Tuple[int, int]:
    """Sort both blocks chronologically on the canonical date and compact them. Returns row counts."""
    _refuse_if_appending(spreadsheet, is_appending)
    counts = []
    with _lock(spreadsheet.id):
        ws = transactions_tab(spreadsheet)
        for block in (EXPENSES, INCOME):
            contents = read_block(spreadsheet, block, worksheet=ws)
            rows = [(t, c) for t, c in zip(contents.tuples, contents.cells) if t]
            ordered = sorted(rows, key=lambda rc: _date_key(rc[0]))     # stable
            counts.append(len(rows))
            if ordered == rows and len(rows) == len(contents.tuples):
                continue
            compact_block(spreadsheet, block, [c for _, c in ordered], is_appending=is_appending,
                          previous_last_row=contents.last_row, worksheet=ws)
            logger.info("Sorted %d %s rows in %s", len(rows), block.name, spreadsheet.id)
    return counts[0], counts[1]


def remove_rows(spreadsheet, block: Block, rows, *, is_appending: IsAppending) -> Tuple[int, int]:
    """
    Remove one occurrence per given RowTuple, never more occurrences of a tuple
    than were passed, then compact. A tuple that cannot be found is skipped.
    Returns (removed, not_found).
    """
    _refuse_if_appending(spreadsheet, is_appending)
    wanted = Counter(tuple(r) for r in rows)
    with _lock(spreadsheet.id):
        ws = transactions_tab(spreadsheet)
        contents = read_block(spreadsheet, block, worksheet=ws)
        keep = [bool(t) for t in contents.tuples]
        removed = 0
        for i in reversed(range(len(contents.tuples))):
            t = contents.tuples[i]
            if t and wanted[t] > 0:
                wanted[t] -= 1
                keep[i] = False
                removed += 1
        if removed:
            compact_block(spreadsheet, block, [c for c, k in zip(contents.cells, keep) if k],
                          is_appending=is_appending, previous_last_row=contents.last_row, worksheet=ws)
    return removed, sum(n for n in wanted.values() if n > 0)
