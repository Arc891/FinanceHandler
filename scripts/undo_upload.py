#!/usr/bin/env python3
"""
Reverse one upload run from its write audit (plan 4.6).

    venv/bin/python scripts/undo_upload.py <upload_id>                  # remove the run's rows
    venv/bin/python scripts/undo_upload.py <upload_id> --drop-created   # also trash months it created
    venv/bin/python scripts/undo_upload.py <upload_id> --dry-run        # print what would happen

Per (sheet, block) it removes the rows the run's audit recorded: content-
addressed, so a sort since the run does not matter, and never more occurrences
of a row than were recorded, so a pre-existing row that merely equals one is
kept. A recorded row that is no longer there is reported as "not found".

Then it restores the period anchor the run started from, and drops the run's
dedup records so an upload of the same export writes those rows again.

Without --drop-created a month the run created stays in Drive and in the
index (emptied). With it, the index entries created by this upload are
removed and those spreadsheets are moved to the Drive bin.

Refuses while any run has a period at `appending`: run /resume first so that
period is reconciled, then undo. Undo compacts blocks, and compacting a
mid-write block would destroy the baseline its recovery depends on.
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from finance_core.config_access import project_path, setting  # noqa: E402
from finance_core.ledger import Ledger  # noqa: E402
from finance_core.period_state import write_state  # noqa: E402
from finance_core.row_tuple import BLOCKS_BY_NAME  # noqa: E402
from finance_core.run_state import appending_sheet_ids  # noqa: E402
from finance_core.sheet_index import load_index, save_index  # noqa: E402
from finance_core.sheet_writer import remove_rows  # noqa: E402


def main(argv=None, *, workbooks=None, stdout_write=sys.stdout.write) -> int:
    parser = argparse.ArgumentParser(description="Reverse one upload run from its write audit.")
    parser.add_argument("upload_id")
    parser.add_argument("--drop-created", action="store_true",
                        help="also trash the months this upload created and remove them from the index")
    parser.add_argument("--dry-run", action="store_true", help="print what would be done, change nothing")
    parser.add_argument("--ledger", default=project_path(setting("UPLOAD_LEDGER_PATH", "data/upload_ledger.json")))
    parser.add_argument("--index", default=project_path(setting("SHEET_INDEX_PATH", "data/sheet_index.json")))
    parser.add_argument("--period-state",
                        default=project_path(setting("PERIOD_STATE_PATH", "data/period_state.json")))
    parser.add_argument("--runs-dir", default=project_path(setting("RUNS_DIR", "data/runs")))
    args = parser.parse_args(argv)

    def say(line=""):
        stdout_write(line + "\n")

    ledger = Ledger(args.ledger)
    run = ledger.run(args.upload_id)
    if run is None:
        say(f"No run {args.upload_id!r} in {args.ledger}.")
        return 1
    if run.get("undone_at"):
        say(f"Run {args.upload_id} was already undone at {run['undone_at']}.")
        return 1

    audit = ledger.audited_rows(args.upload_id)
    appending = appending_sheet_ids(args.runs_dir)
    busy = sorted(set(audit) & appending)
    if busy:
        say(f"Refused: {', '.join(busy)} has a period still `appending`. Run /resume first to reconcile it, "
            "then run this undo again.")
        return 2

    index = load_index(args.index)
    label_of = {entry["id"]: label for label, entry in index.items()}
    drop = {label: entry for label, entry in index.items()
            if args.drop_created and entry.get("created_by_bot") and entry.get("upload_id") == args.upload_id}
    drop_ids = {entry["id"] for entry in drop.values()}

    if workbooks is None and not args.dry_run and (audit or drop):
        from finance_core.sheet_registry import GoogleWorkbooks
        workbooks = GoogleWorkbooks.from_credentials()

    verb = "would remove" if args.dry_run else "removed"
    for sheet_id, blocks in audit.items():
        name = label_of.get(sheet_id, sheet_id)
        if sheet_id in drop_ids:
            say(f"{name}: created by this run; {'would be' if args.dry_run else 'is'} trashed instead")
            continue
        if args.dry_run:
            for block, rows in blocks.items():
                say(f"{name} {block}: {verb} {len(rows)}")
            continue
        sh = workbooks.open(sheet_id)
        for block, rows in blocks.items():
            removed, not_found = remove_rows(sh, BLOCKS_BY_NAME[block], rows,
                                             is_appending=lambda sid: sid in appending)
            say(f"{name} {block}: {verb} {removed}, not found {not_found}")

    for label, entry in drop.items():
        say(f"{label}: {'would trash' if args.dry_run else 'trashed'} {entry['id']} and remove it from the index")
        if not args.dry_run:
            workbooks.trash_file(entry["id"])
            index.pop(label)
            save_index(args.index, index)

    anchor = run.get("anchor_before")
    if args.dry_run:
        say(f"would restore the period state to: {json.dumps(anchor)}")
        return 0
    write_state(args.period_state, anchor)
    say(f"period state restored to: {json.dumps(anchor)}")
    ledger.forget_run(args.upload_id)
    say(f"run {args.upload_id} undone; its rows count as new on the next upload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
