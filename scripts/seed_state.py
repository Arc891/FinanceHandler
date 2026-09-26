#!/usr/bin/env python3
"""
Seed the period anchor and the weak ledger from the monthly sheets
(plan 4.3, 4.6, 4.10; Phase 4 step 3).

    venv/bin/python scripts/seed_state.py                                    # from the sheets
    venv/bin/python scripts/seed_state.py --set-anchor DD-MM-YYYY MM/YYYY    # set the anchor by hand

From the sheets: every sheet in the index is read (both blocks, unformatted).
A sheet's boundary is its earliest row date, across both blocks: everything
dated before the boundary went to the previous sheet, so the earliest row is
the boundary by construction. The newest boundary becomes the anchor, the
rest its history. A sheet with no rows is skipped. Sheet descriptions are
never marker-matched: they are the bot's own text, and neither boundary
marker matches them (section 11). Each populated sheet's rows also seed the
weak ledger under its label, as date | absolute amount | block and nothing
else, so rows the old pipeline wrote are recognised on the next upload.

--set-anchor is the escape hatch of 4.3 rule 5: it sets the anchor to the
given boundary and label, keeps the history older than it, pushes the old
anchor onto the history when it is older, and touches neither the sheets nor
the ledger.

Both print what they would write, dates and labels only, and write nothing
until the user types "yes". Both refuse while any upload run is open.
"""

import argparse
import os
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from finance_core.config_access import project_path, setting  # noqa: E402
from finance_core.ledger import Ledger, weak_key_parts  # noqa: E402
from finance_core.period_state import load_anchor, save_anchor, split_settings  # noqa: E402
from finance_core.periods import Anchor, format_date, label_for_boundary, parse_date  # noqa: E402
from finance_core.row_tuple import BLOCKS, is_iso  # noqa: E402
from finance_core.run_state import RunStore  # noqa: E402
from finance_core.sheet_index import label_sort_key, load_index, parse_label  # noqa: E402
from finance_core.sheet_writer import read_block  # noqa: E402

__all__ = ["main", "parse_date"]


def sheet_rows(spreadsheet) -> dict:
    """{block name: [(iso date, abs amount), ...]} for every dated row."""
    rows = {}
    for block in BLOCKS:
        out = []
        for t in read_block(spreadsheet, block).tuples:
            if not t or not is_iso(t[0]):
                continue
            try:
                amount = abs(Decimal(t[1]))
            except InvalidOperation:
                continue
            out.append((t[0], amount))
        rows[block.name] = out
    return rows


def boundary_of(rows: dict):
    dates = [d for block in rows.values() for d, _ in block]
    return min(dates) if dates else None


def weak_keys(rows: dict) -> list:
    return [weak_key_parts(d, amount, block) for block, items in rows.items() for d, amount in items]


def default_registry():
    from finance_core.sheet_registry import GoogleWorkbooks, RegistryConfig, SheetRegistry
    return SheetRegistry(GoogleWorkbooks.from_credentials(), RegistryConfig.from_settings())


def describe(anchor, split_day) -> list:
    """Anchor and history lines; '!' marks a boundary whose label disagrees with its date."""
    def line(boundary, label):
        expected = label_for_boundary(boundary, split_day)
        flag = "" if expected == label else f"   ! the date gives {expected}; check this sheet"
        return f"  {format_date(boundary)} -> {label}{flag}"
    lines = ["Anchor:", line(anchor.boundary, anchor.label), "History (newest first):"]
    lines += [line(b, lbl) for b, lbl in anchor.history] or ["  (none)"]
    return lines


def main(argv=None, *, registry=None, stdout_write=sys.stdout.write, input_fn=input) -> int:
    parser = argparse.ArgumentParser(description="Seed the period anchor and the weak ledger.")
    parser.add_argument("--set-anchor", nargs=2, metavar=("DD-MM-YYYY", "MM/YYYY"),
                        help="set the anchor by hand instead of reading the sheets")
    parser.add_argument("--index", default=project_path(setting("SHEET_INDEX_PATH", "data/sheet_index.json")))
    parser.add_argument("--ledger", default=project_path(setting("UPLOAD_LEDGER_PATH", "data/upload_ledger.json")))
    parser.add_argument("--period-state",
                        default=project_path(setting("PERIOD_STATE_PATH", "data/period_state.json")))
    parser.add_argument("--runs-dir", default=project_path(setting("RUNS_DIR", "data/runs")))
    args = parser.parse_args(argv)

    def say(line=""):
        stdout_write(line + "\n")

    open_runs = RunStore(args.runs_dir).open_runs()
    if open_runs:
        say("Refused: upload run(s) still open: " + ", ".join(r["upload_id"] for r in open_runs)
            + ". Finish them with /resume or /cancel first.")
        return 2

    split_day = split_settings()["split_day"]
    current = load_anchor(args.period_state)
    say("Current anchor: " + (f"{format_date(current.boundary)} -> {current.label}" if current else "none"))

    seeds = {}
    if args.set_anchor:
        try:
            boundary = parse_date(args.set_anchor[0])
            label = args.set_anchor[1]
            parse_label(label)
            history = []
            if current:
                history = [(b, lbl) for b, lbl in ((current.boundary, current.label),) + current.history
                           if b < boundary]
            anchor = Anchor(boundary, label, tuple(history))
        except ValueError as exc:
            say(f"Refused: {exc}")
            return 2
    else:
        registry = registry or default_registry()
        index = load_index(args.index)
        boundaries = []
        for label in sorted(index, key=label_sort_key):
            spreadsheet = registry.lookup(label)
            rows = sheet_rows(spreadsheet)
            boundary = boundary_of(rows)
            if boundary is None:
                say(f"{label}: no rows, skipped")
                continue
            seeds[label] = weak_keys(rows)
            say(f"{label}: {len(rows['expenses'])} expense and {len(rows['income'])} income row(s)")
            boundaries.append((date.fromisoformat(boundary), label))
        if not boundaries:
            say("No populated sheet in the index; nothing to seed.")
            return 1
        boundaries.sort(reverse=True)
        try:
            anchor = Anchor(boundaries[0][0], boundaries[0][1], tuple(boundaries[1:]))
        except ValueError as exc:
            say(f"Refused: two sheets give the same or crossing boundaries ({exc}). "
                "Check the earliest row of each; nothing was written.")
            return 2

    for line in describe(anchor, split_day):
        say(line)
    target = f"the anchor to {args.period_state}"
    if seeds:
        target += f" and the weak ledger for {len(seeds)} month(s) to {args.ledger}"
    if input_fn(f"Write {target}? Type yes to confirm: ").strip() != "yes":
        say("Nothing written.")
        return 1
    save_anchor(args.period_state, anchor)
    if seeds:
        ledger = Ledger(args.ledger)
        for label, keys in seeds.items():
            ledger.seed_label(label, keys)
    say(f"Written: {target}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
