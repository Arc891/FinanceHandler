#!/usr/bin/env python3
"""Plan historical description notes from one ASN export for 06-10/2026.

Dry run by default. Output contains counts only: no transaction values, sheet
IDs, row numbers, or note text. Run this yourself with the original export and
the authoritative sheet index. It reads private rows locally to match them;
do not share its input or a debug trace. An apply needs the owner's separate
approval and ``--apply --confirm backfill-notes``.

    venv/bin/python scripts/backfill_notes.py --csv /private/export.csv
    venv/bin/python scripts/backfill_notes.py --csv /private/export.csv --apply --confirm backfill-notes

Rows match within each expense/income block by exact date and amount, with
equal multiplicity. Exact bank name/remittance text only breaks a tie. A
disputed match is skipped. Existing notes are never overwritten; before each
write the script checks that both the row values and destination notes stayed
unchanged. Older AI guesses cannot be reconstructed from the bank export.
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from finance_core.config_access import project_path, setting  # noqa: E402
from finance_core.row_tuple import BLOCKS, canonical_date  # noqa: E402
from finance_core.sheet_index import load_index  # noqa: E402
from finance_core.sheet_writer import bank_note, read_block, read_notes  # noqa: E402

MONTHS = tuple(f"{month:02d}/2026" for month in range(6, 11))


@dataclass(frozen=True)
class ExportRow:
    block: str
    date: str
    amount: str
    note: str
    hints: tuple[str, ...] = ()

    @property
    def key(self):
        return self.block, self.date, self.amount


@dataclass
class BlockPlan:
    changes: dict[str, str]
    counts: Counter


def _amount(value):
    amount = Decimal(str(value).strip().replace(",", "."))
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        raise ValueError("invalid amount")
    return amount


def parse_export_rows(rows):
    """Parse only the fields needed for matching and bank notes, without writing a copy."""
    found, invalid = [], 0
    for row in rows:
        try:
            if len(row) < 18:
                raise ValueError("short row")
            day = canonical_date(row[0].strip())
            date.fromisoformat(day)
            amount = _amount(row[10])
            if amount == 0:
                raise ValueError("zero amount")
            if row[9].strip().upper() != "EUR":
                raise ValueError("currency")
            block = "expenses" if amount < 0 else "income"
            name, account, remittance = row[3].strip(), row[2].strip(), row[17].strip()
            tx = {"debtor": {"name": name if block == "expenses" else ""},
                  "creditor": {"name": name if block == "income" else ""},
                  "counterparty_iban": account, "remittance_information": [remittance] if remittance else []}
            hints = tuple(v for v in (name, remittance) if v)
            found.append(ExportRow(block, day, f"{abs(amount):.2f}", bank_note(tx), hints))
        except (InvalidOperation, ValueError, OverflowError, IndexError):
            invalid += 1
    return found, invalid


def _same_text(value):
    return str(value or "").strip().casefold()


def _resolved_notes(sheet_group, source_group):
    notes = {item.note for item in source_group}
    if len(notes) == 1:
        return [source_group[0].note] * len(sheet_group)
    chosen, used = [], set()
    for _, description in sheet_group:
        text = _same_text(description)
        candidates = [i for i, item in enumerate(source_group)
                      if i not in used and text and any(text == _same_text(h) for h in item.hints)]
        if len(candidates) != 1:
            return None
        selected = candidates[0]
        used.add(selected)
        chosen.append(source_group[selected].note)
    return chosen if len(used) == len(source_group) else None


def plan_block(block, contents, notes, exports, *, excluded=frozenset()):
    """Return only unambiguous writes into blank description notes."""
    source = defaultdict(list)
    for item in exports:
        if item.block == block.name:
            source[item.key].append(item)
    sheet = defaultdict(list)
    for offset, cells in enumerate(contents.tuples):
        if cells:
            sheet[(block.name, cells[0], cells[1])].append((offset, cells[2]))
    changes, counts = {}, Counter()
    note_col = chr(ord(block.first_col) + 2)
    for key, group in sheet.items():
        candidates = source.get(key, [])
        if key in excluded or (candidates and len(group) != len(candidates)):
            counts["ambiguous"] += len(group)
            continue
        if not candidates:
            counts["unmatched"] += len(group)
            continue
        assigned = _resolved_notes(group, candidates)
        if assigned is None:
            counts["ambiguous"] += len(group)
            continue
        for (offset, _), note in zip(group, assigned):
            if offset < len(notes) and notes[offset]:
                counts["occupied"] += 1
            elif not note:
                counts["no_bank_detail"] += 1
            else:
                changes[f"{note_col}{contents.start + offset}"] = note
                counts["planned"] += 1
    return BlockPlan(changes, counts)


def apply_block(spreadsheet, block, baseline, plan):
    """Return False if rows or target notes changed since planning; never overwrite a note."""
    if not plan.changes:
        return True
    ws = spreadsheet.worksheet("Transactions")
    current = read_block(spreadsheet, block, worksheet=ws)
    if current.tuples != baseline.tuples:
        return False
    notes = read_notes(ws, block, current.start, current.last_row)
    if any(notes[int(a1[1:]) - current.start] for a1 in plan.changes):
        return False
    ws.update_notes(plan.changes)
    stored = read_notes(ws, block, current.start, current.last_row)
    if any(stored[int(a1[1:]) - current.start] != note for a1, note in plan.changes.items()):
        raise RuntimeError("note readback did not match the requested update")
    return True


def run(csv_path, index_path, *, apply=False, workbooks=None, out=print):
    written = 0
    try:
        index = load_index(index_path)
        if any(label not in index for label in MONTHS):
            out("refused: authoritative index is missing a target month")
            return 1
        if len({index[label]["id"] for label in MONTHS}) != len(MONTHS):
            out("refused: duplicate sheet registration among target months")
            return 1
        with open(csv_path, newline="", encoding="utf-8") as handle:
            exports, invalid = parse_export_rows(csv.reader(handle))
        if invalid or not exports:
            out(f"refused: export has {invalid} invalid row(s) or no usable rows")
            return 1
        if workbooks is None:
            from finance_core.sheet_registry import GoogleWorkbooks
            workbooks = GoogleWorkbooks.from_credentials()
        opened = {}
        occurrences = defaultdict(set)
        for label in MONTHS:
            spreadsheet = workbooks.open(index[label]["id"])
            expected_title = setting("GSHEET_NAME_PATTERN", "Maandelijks Budget {label}").format(label=label)
            if spreadsheet.title != expected_title:
                out(f"refused: wrong sheet title for {label}")
                return 1
            ws = spreadsheet.worksheet("Transactions")
            blocks = []
            for block in BLOCKS:
                contents = read_block(spreadsheet, block, worksheet=ws)
                notes = read_notes(ws, block, contents.start, contents.last_row)
                blocks.append((block, contents, notes))
                for cells in contents.tuples:
                    if cells:
                        occurrences[(block.name, cells[0], cells[1])].add(label)
            opened[label] = (spreadsheet, blocks)
        excluded = {key for key, labels in occurrences.items() if len(labels) > 1}
        plans = {}
        totals = Counter()
        for label, (_, blocks) in opened.items():
            per_month = Counter()
            plans[label] = []
            for block, contents, notes in blocks:
                plan = plan_block(block, contents, notes, exports, excluded=excluded)
                per_month.update(plan.counts)
                plans[label].append((block, contents, plan))
            totals.update(per_month)
            out(f"{label}: " + ", ".join(f"{kind}={per_month[kind]}" for kind in
                ("planned", "occupied", "unmatched", "ambiguous", "no_bank_detail")))
        out(f"TOTAL: planned={totals['planned']}, invalid_export_rows={invalid}")
        if not apply:
            out("DRY RUN: no notes written")
            return 0
        for label, (spreadsheet, _) in opened.items():
            for block, baseline, plan in plans[label]:
                if not apply_block(spreadsheet, block, baseline, plan):
                    out(f"refused: {label} changed during the run; {written} note(s) already written")
                    return 1
                written += len(plan.changes)
        out(f"APPLIED: {written} note(s)")
        return 0
    except Exception as exc:
        if apply:
            out(f"refused: {type(exc).__name__}; apply may be partial; {written} note(s) in earlier batches")
        else:
            out(f"refused: {type(exc).__name__}; no writes attempted")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="original ASN export (kept private)")
    parser.add_argument("--index", default=project_path(setting("SHEET_INDEX_PATH", "data/sheet_index.json")),
                        help="authoritative month index")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["backfill-notes"])
    args = parser.parse_args(argv)
    if args.apply and args.confirm != "backfill-notes":
        print("refused: --apply needs --confirm backfill-notes")
        return 1
    return run(args.csv, args.index, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
