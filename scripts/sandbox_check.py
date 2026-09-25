#!/usr/bin/env python3
"""
Phase 1 live check against the real Google APIs (plan section 6). Synthetic data only.

    venv/bin/python scripts/sandbox_check.py            # create, check, delete
    venv/bin/python scripts/sandbox_check.py --keep     # leave the sandbox month for a look

Creates one sandbox month "SANDBOX Maandelijks Budget 12/2099" from the
template through sheet_registry.create, with a scratch index, so the real
data/sheet_index.json is never touched. Then:

  1. create + the full 4.4 step-6 fidelity check, including the behavioural
     totals check (E26, K26, E17 move by a flagged row's amount and return);
     this is the plan A / plan B decision;
  2. whether drive.file may move the new file into the Financiën folder;
  3. the RowTuple round-trip under the real nl_NL workbook:
     canonical(intended) == read_block(...)[-n:];
  4. a sort: amounts identical before and after, dates still render as dates,
     no stale tail;
  5. undo from a scratch ledger's audit: the blocks end empty;
  6. deletes the sandbox month (unless --keep).

It reads only the template's properties and the sandbox month it creates.
Needs the OAuth token from scripts/google_login.py.
"""

import argparse
import os
import sys
import tempfile
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from gspread.utils import ValueRenderOption  # noqa: E402

from finance_core.ledger import Ledger  # noqa: E402
from finance_core.row_tuple import EXPENSES, INCOME, canonical  # noqa: E402
from finance_core.sheet_registry import RegistryConfig, SheetRegistry  # noqa: E402
from finance_core.sheet_writer import (commit_append, intended_cells, read_block,  # noqa: E402
                                       remove_rows, sort_by_date)

LABEL = "12/2099"
PATTERN = "SANDBOX Maandelijks Budget {label}"
NOT_APPENDING = lambda sheet_id: False  # noqa: E731


def synthetic(date_str, amount, description, category="! Nog in te delen !", seq="0"):
    income = not amount.startswith("-")
    name = "Sandbox Tegenpartij"
    return {
        "booking_date": date_str,
        "transaction_amount": {"amount": amount, "currency": "EUR"},
        "credit_debit_indicator": "CRDT" if income else "DBIT",
        "debtor": {"name": "" if income else name},
        "creditor": {"name": name if income else ""},
        "remittance_information": ["sandbox"],
        "remittance_raw": "sandbox",
        "bank_sequence_no": f"sandbox-{seq}",
        "description": description,
        "category": category,
    }


EXPENSE_ROWS = [
    synthetic("20-12-2099", "-1234.56", "Sandbox thousands, comma", seq="1"),
    synthetic("03-12-2099", "-12.00", "Sandbox whole amount", seq="2"),
    synthetic("11-12-2099", "-0.99", "Sandbox cents", seq="3"),
]
INCOME_ROWS = [
    synthetic("24-12-2099", "314.10", "Sandbox income", seq="4"),
    synthetic("01-12-2099", "5.00", "Sandbox early income", seq="5"),
]
PROBE = synthetic("15-12-2099", "-1.00", "2-3", seq="6")     # a description that looks like a date


class Report:
    def __init__(self, say):
        self.say = say
        self.failed = 0

    def check(self, name, ok, detail=""):
        self.say(f"  [{'PASS' if ok else 'FAIL'}] {name}{': ' + detail if detail else ''}")
        self.failed += 0 if ok else 1
        return ok

    def note(self, name, detail):
        self.say(f"  [INFO] {name}: {detail}")


def run_checks(workbooks, say, keep=False, template_id=None) -> int:
    report = Report(say)
    scratch = tempfile.mkdtemp(prefix="sandbox_check.")
    cfg = RegistryConfig.from_settings()
    cfg = RegistryConfig(index_path=os.path.join(scratch, "sheet_index.json"),
                         template_id=template_id or cfg.template_id,
                         folder_id=cfg.folder_id, name_pattern=PATTERN, auto_create=True)
    registry = SheetRegistry(workbooks, cfg)
    ledger = Ledger(os.path.join(scratch, "upload_ledger.json"))
    sheet_id = None

    say(f"1. create {PATTERN.format(label=LABEL)} from the template, with the fidelity check")
    try:
        resolved = registry.resolve(LABEL, upload_id="sandbox")
    except Exception as exc:
        report.check("create + fidelity check (plan A)", False, f"{type(exc).__name__}: {exc}")
        say("\nPlan A failed at creation. Three such failures trigger plan B (plan 4.4 step 6).")
        return 1
    sh = resolved.spreadsheet
    sheet_id = sh.id
    report.check("create + fidelity check (plan A)", True, f"id {sheet_id}")
    try:
        say("2. folder placement under drive.file")
        report.note("moved into GSHEET_FOLDER_ID", "no, left in My Drive root" if resolved.left_in_root else "yes")

        say("3. RowTuple round-trip under nl_NL")
        ledger.start_run("sandbox", None)
        for block, txs in ((EXPENSES, EXPENSE_ROWS), (INCOME, INCOME_ROWS)):
            ledger.record_written("sandbox", LABEL, txs)
            pairs = commit_append(sh, block, txs, failed_path=os.path.join(scratch, "failed.json"))
            ledger.record_audit("sandbox", sheet_id, block.name, pairs)
            intended = [canonical(intended_cells(t)) for t in txs]
            back = read_block(sh, block).tuples[-len(txs):]
            report.check(f"{block.name}: canonical(intended) == read_block[-{len(txs)}:]", intended == back,
                         "" if intended == back else f"intended {intended} read back {back}")
        ws = sh.worksheet("Transactions")
        raw = ws.get("B5:E7", value_render_option=ValueRenderOption.unformatted)
        report.check("dates are stored as serials, amounts as numbers",
                     all(isinstance(r[0], (int, float)) and isinstance(r[1], (int, float)) for r in raw), str(raw))

        probe_pairs = commit_append(sh, EXPENSES, [PROBE], failed_path=os.path.join(scratch, "failed.json"))
        ledger.record_audit("sandbox", sheet_id, EXPENSES.name, probe_pairs)
        probe_back = read_block(sh, EXPENSES).tuples[-1]
        report.note("description '2-3' written USER_ENTERED reads back as", repr(probe_back[2]))

        say("4. sort")
        before = {t[2]: (t[1], c[1]) for t, c in zip(*[getattr(read_block(sh, EXPENSES), a)
                                                        for a in ("tuples", "cells")]) if t}
        sort_by_date(sh, is_appending=NOT_APPENDING)
        after_block = read_block(sh, EXPENSES)
        after = {t[2]: (t[1], c[1]) for t, c in zip(after_block.tuples, after_block.cells) if t}
        report.check("amounts identical before and after the sort", before == after)
        dates = [t[0] for t in after_block.tuples]
        report.check("expenses in date order", dates == sorted(dates), str(dates))
        shown = ws.get(f"B5:C{after_block.last_row}")
        report.check("dates still render as DD-MM-YYYY after RAW compaction",
                     all(len(r) > 0 and r[0].count("-") == 2 and not r[0].isdigit() for r in shown), str(shown))
        report.note("amounts render as", str([r[1] for r in shown if len(r) > 1]))

        say("5. undo from the audit")
        for sid, blocks in ledger.audited_rows("sandbox").items():
            for name, rows in blocks.items():
                block = EXPENSES if name == "expenses" else INCOME
                removed, not_found = remove_rows(sh, block, rows, is_appending=NOT_APPENDING)
                report.check(f"{name}: removed {removed}, not found {not_found}", not_found == 0)
        empty = read_block(sh, EXPENSES).tuples == [] and read_block(sh, INCOME).tuples == []
        report.check("both blocks empty after undo (tail blanked, nothing left behind)", empty)
    except Exception:
        report.check("unexpected error", False, traceback.format_exc())
    finally:
        if keep:
            say(f"6. kept: https://docs.google.com/spreadsheets/d/{sheet_id}")
        else:
            workbooks.delete_file(sheet_id)
            say(f"6. deleted the sandbox month {sheet_id}")

    say(f"\n{'ALL PASSED' if not report.failed else f'{report.failed} FAILED'}")
    return 0 if not report.failed else 1


def main(argv=None, *, workbooks=None, stdout_write=sys.stdout.write) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 live sandbox check (synthetic data only).")
    parser.add_argument("--keep", action="store_true", help="do not delete the sandbox month afterwards")
    parser.add_argument("--template", help="template spreadsheet id (default GSHEET_TEMPLATE_ID)")
    args = parser.parse_args(argv)
    if workbooks is None:
        from finance_core.sheet_registry import GoogleWorkbooks
        workbooks = GoogleWorkbooks.from_credentials()
    return run_checks(workbooks, lambda line="": stdout_write(line + "\n"), keep=args.keep,
                      template_id=args.template)


if __name__ == "__main__":
    sys.exit(main())
