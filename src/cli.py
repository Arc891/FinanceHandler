#!/usr/bin/env python3
"""
finance: the headless, Discord-free command line (spec Decision 1).

    src/cli.py age [--json]     backlog age for the weekly digest
    src/cli.py ingest           not implemented yet (spec P2)

Runs with the system python3: stdlib and finance_core only, no venv, no Docker,
no config needed. It finds its own src/ through the real path of this file, so
a symlink (e.g. ~/bin/finance) works too.

`age --json` prints exactly one line and always exits 0, because staleness is
the signal (spec Decision 5; data source in docs/ingest-notes.md, amendment 5a):

    {"days_since_last_statement": <int|null>, "pending_review_rows": <int|null>}

- days_since_last_statement: Europe/Amsterdam calendar days since the newest
  run in RUNS_DIR closed "complete" (by closed_at), leaving out runs the ledger
  marks undone; null when there is none.
- pending_review_rows: rows of every period not yet `written` in open runs,
  the rows only /resume can still write.

An unreadable run file or ledger gives null for both values and one line on
stderr, never a path or a traceback. Output never names files, upload ids,
descriptions or amounts. `--runs-dir` and `--ledger` override the configured
paths (tests, inspection of a copy).
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from finance_core.ledger import Ledger  # noqa: E402
from finance_core.run_state import WRITTEN, RunStore  # noqa: E402

TZ_NAME = "Europe/Amsterdam"
INGEST_STUB = "finance ingest: not implemented yet, see ~/Coding/specs/finance-ingest.md step 5"
UNREADABLE = "finance age: unreadable run state"


class UnreadableState(Exception):
    """A run file or the ledger could not be read or has an unexpected shape."""


def _parse_closed_at(value) -> datetime:
    if not isinstance(value, str):
        raise UnreadableState("closed_at missing")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise UnreadableState("closed_at unparsable") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _period_rows(period: dict) -> int:
    counts = period.get("counts") or {}
    if isinstance(counts.get("rows"), int) and not isinstance(counts.get("rows"), bool):
        return counts["rows"]
    rows = period.get("rows") or {}
    return len(rows.get("expenses") or []) + len(rows.get("income") or [])


def backlog_age(runs_dir=None, ledger_path=None, now: Optional[datetime] = None
                ) -> Tuple[Optional[int], Optional[date], int]:
    """
    (days_since_last_statement, Amsterdam date of that statement, pending_review_rows).

    Raises UnreadableState when a run file or the ledger cannot be used.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(TZ_NAME)
    now = now or datetime.now(timezone.utc)
    try:
        runs = RunStore(runs_dir).all_runs()
        pending = 0
        complete = []
        for run in runs:
            closed = run.get("closed")
            if closed is None:
                for period in run.get("periods") or []:
                    if period.get("status") != WRITTEN:
                        pending += _period_rows(period)
            elif closed == "complete":
                complete.append((_parse_closed_at(run.get("closed_at")), run.get("upload_id")))

        ledger = Ledger(ledger_path) if ledger_path is not None else Ledger.from_settings()
        newest = None
        for closed_at, upload_id in sorted(complete, key=lambda c: c[0], reverse=True):
            entry = ledger.run(upload_id)
            if entry and entry.get("undone_at"):
                continue
            newest = closed_at
            break
    except UnreadableState:
        raise
    except Exception as exc:  # any unreadable or malformed state file
        raise UnreadableState(type(exc).__name__) from exc

    if newest is None:
        return None, None, pending
    statement_day = newest.astimezone(tz).date()
    days = (now.astimezone(tz).date() - statement_day).days
    return max(days, 0), statement_day, pending


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _age(args, now: Optional[datetime]) -> int:
    try:
        days, day, pending = backlog_age(args.runs_dir, args.ledger, now)
    except UnreadableState:
        days, day, pending = None, None, None
        unreadable = True
    else:
        unreadable = False

    if args.json:
        print(json.dumps({"days_since_last_statement": days, "pending_review_rows": pending}))
    elif unreadable:
        print("backlog age unknown: run state unreadable")
    else:
        pending_text = f"{_plural(pending, 'row')} pending in open runs"
        if days is None:
            print(f"no imported statement on record; {pending_text}")
        else:
            print(f"last statement imported {_plural(days, 'day')} ago ({day.isoformat()}); {pending_text}")
    if unreadable:
        print(UNREADABLE, file=sys.stderr)
    return 0


def _ingest(args, now) -> int:
    print(INGEST_STUB, file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finance", description="Headless finance commands.")
    sub = parser.add_subparsers(dest="command", required=True)

    age = sub.add_parser("age", help="days since the last imported statement, and rows pending")
    age.add_argument("--json", action="store_true", help="one JSON line (the digest contract)")
    age.add_argument("--runs-dir", default=None, help="run files directory (default: RUNS_DIR)")
    age.add_argument("--ledger", default=None, help="upload ledger (default: UPLOAD_LEDGER_PATH)")
    age.set_defaults(handler=_age)

    ingest = sub.add_parser("ingest", help="not implemented yet")
    ingest.set_defaults(handler=_ingest)
    return parser


def main(argv=None, *, now: Optional[datetime] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args, now)


if __name__ == "__main__":
    sys.exit(main())
