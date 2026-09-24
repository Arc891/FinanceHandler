#!/usr/bin/env python3
"""
Seed and edit data/sheet_index.json, the authoritative month -> sheet index.

The bot cannot search Drive (it has no Drive listing scope), so this index is
the only record of which spreadsheet holds which month. Nothing here talks to
Google; the bot verifies each sheet when it first opens it.

Usage:
    venv/bin/python scripts/register_sheets.py seed                  # the 2026 months below
    venv/bin/python scripts/register_sheets.py add 07/2026 <url-or-id> [--force]
    venv/bin/python scripts/register_sheets.py paste < list.txt      # "MM/YYYY <url-or-id>" per line
    venv/bin/python scripts/register_sheets.py list

All commands take --index PATH (default data/sheet_index.json). A command that
would repoint an existing month, or register one sheet as two months, changes
nothing and exits 1; `add --force` overrides that for one month.
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from finance_core.sheet_index import (  # noqa: E402
    extract_spreadsheet_id,
    label_sort_key,
    load_index,
    register,
    save_index,
)

DEFAULT_INDEX_PATH = os.path.join(PROJECT_ROOT, "data", "sheet_index.json")

# Collected 2026-09-21 (plan section 11). Folder `Financiën`
# 1QoYs19vu04_DFIszlfWOJP7BoQLEtfaG. 2024 and 2025 are out of scope.
SEED_SHEETS = {
    "01/2026": "1PE0gjLFBcO119H0p3EWD-InVzV2a8IA86utN8dF_UHw",
    "02/2026": "1-REOGzjHlOdXRQR1UOor-BA3KvPLesRqV-ks3P3zRG0",
    "03/2026": "1HXMu53v1T-gFsC8YREL9VScNsIs4h_CG-BSYw6EMwm4",
    "04/2026": "1hLCziEA-8MgupWHC5gLDLpmd3ZJlrWZcbMwnCfk6f4M",
    "05/2026": "1lOmS_Cd3vqoZyi-4SBrT3GTrRP9akqcO8l_0uWUlXM8",
    "06/2026": "14t0lxRlrCyXmpBk8heWBFOxzgVeG15YxdqjROp5t0Jw",
}


def _apply(path, pairs, out, force=False) -> int:
    """Register every (label, url_or_id) pair, or change nothing."""
    try:
        index = load_index(path)
    except ValueError as exc:
        print(f"error: {exc}", file=out)
        return 1
    counts = {"added": 0, "unchanged": 0, "replaced": 0}
    errors = []
    for where, label, url_or_id in pairs:
        try:
            counts[register(index, label, extract_spreadsheet_id(url_or_id), force=force)] += 1
        except ValueError as exc:
            errors.append(f"{where}: {exc}")
    if errors:
        for line in errors:
            print(f"error: {line}", file=out)
        print(f"nothing written to {path}", file=out)
        return 1
    if counts["added"] or counts["replaced"]:
        save_index(path, index)
    print(f"{path}: {counts['added']} added, {counts['unchanged']} unchanged, "
          f"{counts['replaced']} replaced, {len(index)} months total", file=out)
    return 0


def _parse_pasted(text):
    pairs, errors = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            errors.append(f"line {n}: expected 'MM/YYYY <url-or-id>', got {raw!r}")
            continue
        pairs.append((f"line {n}", parts[0], parts[1]))
    return pairs, errors


def main(argv, stdin=sys.stdin, stdout=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", default=DEFAULT_INDEX_PATH, help="index file (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="register the 2026 months recorded in the plan")
    add = sub.add_parser("add", help="register one month")
    add.add_argument("label", help="MM/YYYY")
    add.add_argument("sheet", help="spreadsheet URL or id")
    add.add_argument("--force", action="store_true", help="repoint a month that is already registered")
    sub.add_parser("paste", help="read 'MM/YYYY <url-or-id>' lines from stdin")
    sub.add_parser("list", help="print the index")
    for p in sub.choices.values():
        p.add_argument("--index", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.command == "seed":
        return _apply(args.index, [(label, label, sid) for label, sid in SEED_SHEETS.items()], stdout)
    if args.command == "add":
        return _apply(args.index, [(args.label, args.label, args.sheet)], stdout, force=args.force)
    if args.command == "paste":
        pairs, errors = _parse_pasted(stdin.read())
        if errors:
            for line in errors:
                print(f"error: {line}", file=stdout)
            print(f"nothing written to {args.index}", file=stdout)
            return 1
        return _apply(args.index, pairs, stdout)

    try:
        index = load_index(args.index)
    except ValueError as exc:
        print(f"error: {exc}", file=stdout)
        return 1
    if not index:
        print(f"{args.index}: empty", file=stdout)
    for label in sorted(index, key=label_sort_key):
        entry = index[label]
        origin = "created by bot" if entry.get("created_by_bot") else "registered"
        print(f"{label}  https://docs.google.com/spreadsheets/d/{entry['id']}  ({origin})", file=stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
