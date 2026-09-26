#!/usr/bin/env python3
"""
Re-append the rows of failed sheet writes (plan 4.10, Phase 4 step 1).

    venv/bin/python scripts/retry_failed_transactions.py             # retry every entry
    venv/bin/python scripts/retry_failed_transactions.py --dry-run   # print what would happen

A failed write (sheet_writer.commit_append) leaves an entry in
data/failed_uploads.json with the rows, their upload_id, period_label and
block. Per entry this script:

- skips it, and keeps it, while its run is still open: that run holds the
  same rows and /resume reconciles and writes them, so writing them here as
  well would write them twice;
- opens the sheet for period_label through the index (never creates one);
- skips every row the block already holds, as a multiset: the failed write
  may have landed after all;
- appends the rest in one write, audits them in the ledger under the entry's
  upload_id (so undo_upload.py reverses them with the rest of that run), and
  drops the entry. A failing append keeps the entry and counts the attempt.

Entries in the old pipeline's format (no period_label or block) are reported
and left alone. It prints counts only, never row content. Run it while no
upload is in progress: the bot appends to the same file during a run. The
closing sort is not done here; run /sort for the months it names.
"""

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from finance_core.config_access import project_path, setting  # noqa: E402
from finance_core.ledger import Ledger  # noqa: E402
from finance_core.row_tuple import BLOCKS_BY_NAME, canonical  # noqa: E402
from finance_core.run_state import RunStore  # noqa: E402
from finance_core.sheet_writer import (DEFAULT_FAILED_PATH, commit_append,  # noqa: E402
                                       intended_cells, read_block)


def load_entries(path) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh) or {}
    return list(data.get("failed", []))


def save_entries(path, entries) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".failed.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"failed": entries}, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def is_current(entry) -> bool:
    """Written by sheet_writer.commit_append, not by the old upload queue."""
    return (isinstance(entry, dict) and entry.get("period_label")
            and entry.get("block") in BLOCKS_BY_NAME
            and isinstance(entry.get("transactions"), list))


def owed_rows(spreadsheet, block, txs) -> list:
    """The rows of ``txs`` the block does not already hold, as a multiset."""
    present = Counter(t for t in read_block(spreadsheet, block).tuples if t)
    owed = []
    for tx in txs:
        cells = canonical(intended_cells(tx))
        if present[cells] > 0:
            present[cells] -= 1
        else:
            owed.append(tx)
    return owed


def default_registry():
    from finance_core.sheet_registry import GoogleWorkbooks, RegistryConfig, SheetRegistry
    return SheetRegistry(GoogleWorkbooks.from_credentials(), RegistryConfig.from_settings())


def main(argv=None, *, registry=None, stdout_write=sys.stdout.write) -> int:
    parser = argparse.ArgumentParser(description="Re-append the rows of failed sheet writes.")
    parser.add_argument("--dry-run", action="store_true", help="print what would be done, change nothing")
    parser.add_argument("--failed",
                        default=project_path(setting("FAILED_UPLOADS_PATH", DEFAULT_FAILED_PATH)))
    parser.add_argument("--runs-dir", default=project_path(setting("RUNS_DIR", "data/runs")))
    parser.add_argument("--ledger", default=project_path(setting("UPLOAD_LEDGER_PATH", "data/upload_ledger.json")))
    args = parser.parse_args(argv)

    def say(line=""):
        stdout_write(line + "\n")

    entries = load_entries(args.failed)
    if not entries:
        say(f"Nothing to retry: {args.failed} holds no failed writes.")
        return 0

    open_ids = {r["upload_id"] for r in RunStore(args.runs_dir).open_runs()}
    ledger = Ledger(args.ledger)
    keep, problems, touched = [], 0, []
    with tempfile.TemporaryDirectory() as scratch:
        # commit_append records its own failure; this script keeps the entry instead.
        scratch_failed = os.path.join(scratch, "failed.json")
        for i, entry in enumerate(entries, start=1):
            if not is_current(entry):
                say(f"entry {i}: old format (no period_label or block); left in the file")
                keep.append(entry)
                continue
            label, block_name, txs = entry["period_label"], entry["block"], entry["transactions"]
            upload_id = entry.get("upload_id")
            where = f"entry {i} ({label} {block_name}, {len(txs)} row(s), upload {upload_id})"
            if upload_id in open_ids:
                say(f"{where}: skipped, its open run holds these rows; /resume {upload_id} writes them")
                keep.append(entry)
                continue

            try:
                registry = registry or default_registry()
                spreadsheet = registry.lookup(label)
            except Exception as exc:
                say(f"{where}: cannot open the sheet ({type(exc).__name__}); kept")
                keep.append(entry)
                problems += 1
                continue
            if spreadsheet is None:
                say(f"{where}: {label} is not in the index; add it with /months register, then retry")
                keep.append(entry)
                problems += 1
                continue

            block = BLOCKS_BY_NAME[block_name]
            owed = owed_rows(spreadsheet, block, txs)
            already = len(txs) - len(owed)
            if args.dry_run:
                say(f"{where}: would append {len(owed)}, already in the sheet {already}")
                keep.append(entry)
                continue
            if owed:
                try:
                    pairs = commit_append(spreadsheet, block, owed,
                                          context={"upload_id": upload_id, "period_label": label},
                                          failed_path=scratch_failed)
                except Exception as exc:
                    entry = dict(entry, error=f"{type(exc).__name__}: {exc}",
                                 attempts=entry.get("attempts", 0) + 1,
                                 failed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    say(f"{where}: append failed ({type(exc).__name__}); kept for the next retry")
                    keep.append(entry)
                    problems += 1
                    save_entries(args.failed, keep + entries[i:])
                    continue
                ledger.record_audit(upload_id or "retry", spreadsheet.id, block_name, pairs)
                if label not in touched:
                    touched.append(label)
            say(f"{where}: appended {len(owed)}, already in the sheet {already}")
            # After every entry, so a crash never loses one; a rerun skips rows already written.
            save_entries(args.failed, keep + entries[i:])

    if touched:
        say("Sort the months written to: " + ", ".join(f"/sort {label}" for label in touched))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
