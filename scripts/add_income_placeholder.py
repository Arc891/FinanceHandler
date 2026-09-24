#!/usr/bin/env python3
"""
Add the income placeholder category `! Nog in te delen !` to the monthly sheets.

The income category table on the Summary tab ends at H34. K35 already holds
    =if(isblank($H35); ""; sumif(Transactions!$J:$J;$H35;Transactions!$H:$H))
and the income total K26 = sum(K27:K44) already covers row 35, so writing the
label into H35 is the whole change: it switches that SUMIF on, and the income
category dropdown (Summary!$H$27:$I$44) offers it. No formula, row or range is
touched (plan 4.9, section 11).

Per sheet the script refuses to write when H35 holds anything else, or when
K35 is not that guarded SUMIF. A sheet that already has the label is skipped.

Targets: the template plus every month in register_sheets.SEED_SHEETS.

Usage:
    venv/bin/python scripts/add_income_placeholder.py                 # dry run: reads only
    venv/bin/python scripts/add_income_placeholder.py --apply         # write H35
    venv/bin/python scripts/add_income_placeholder.py --apply --only template

Uses the service account in GOOGLE_CREDENTIALS_PATH, which has edit access to
the Financiën folder. Exit status is 0 only if no sheet was refused or failed.
"""

import argparse
import os
import sys
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

from register_sheets import SEED_SHEETS  # noqa: E402

LABEL = "! Nog in te delen !"
TARGET_CELL = "H35"
GUARD_CELL = "K35"
EXPECTED_GUARD = '=if(isblank($H35); ""; sumif(Transactions!$J:$J;$H35;Transactions!$H:$H))'
TEMPLATE_ID = "1OSi4W3B3PrfCTQyxt3OreLmqSs4nXY82Wlg1_eohTs8"
ROLLBACK = ("Rollback: clear Summary!H35 on the affected sheet, or restore it from "
            "File > Version history. Nothing else is changed.")


def targets():
    return [("template", TEMPLATE_ID)] + list(SEED_SHEETS.items())


def _normalise_formula(formula: str) -> str:
    # Sheets may return ';' or ',' separators depending on locale and API path.
    return "".join((formula or "").split()).lower().replace(";", ",")


@dataclass
class Result:
    action: str   # would-write | written | already-done | refused | failed | error
    detail: str


def patch_summary(tab, apply: bool) -> Result:
    """Check one Summary tab and, if ``apply``, write the label into H35."""
    guard = tab.read_formula(GUARD_CELL)
    if _normalise_formula(guard) != _normalise_formula(EXPECTED_GUARD):
        return Result("refused", f"{GUARD_CELL} is {guard!r}, expected the guarded SUMIF on $H35")
    current = (tab.read_value(TARGET_CELL) or "").strip()
    if current == LABEL:
        return Result("already-done", f"{TARGET_CELL} already reads {LABEL!r}")
    if current:
        return Result("refused", f"{TARGET_CELL} is not empty: {current!r}")
    if not apply:
        return Result("would-write", f"{TARGET_CELL}: '' -> {LABEL!r}")
    tab.write_text(TARGET_CELL, LABEL)
    after = (tab.read_value(TARGET_CELL) or "").strip()
    if after != LABEL:
        return Result("failed", f"wrote {TARGET_CELL} but it reads back as {after!r}")
    return Result("written", f"{TARGET_CELL} = {LABEL!r}")


class GspreadSummary:
    """The three cell operations patch_summary needs, on a gspread worksheet."""

    def __init__(self, worksheet):
        self.ws = worksheet

    def read_value(self, cell):
        return self.ws.acell(cell).value or ""

    def read_formula(self, cell):
        from gspread.utils import ValueRenderOption
        return self.ws.acell(cell, value_render_option=ValueRenderOption.formula).value or ""

    def write_text(self, cell, value):
        from gspread.utils import ValueInputOption
        self.ws.update(range_name=cell, values=[[value]], value_input_option=ValueInputOption.raw)


def service_account_opener():
    import gspread
    from google.oauth2.service_account import Credentials
    from config.config_settings import GOOGLE_CREDENTIALS_PATH

    creds = Credentials.from_service_account_file(
        os.path.join(PROJECT_ROOT, GOOGLE_CREDENTIALS_PATH),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)

    def open_summary(name, sheet_id):
        return GspreadSummary(gc.open_by_key(sheet_id).worksheet("Summary"))
    return open_summary


def run(argv, open_summary, out=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write H35 (default: dry run, reads only)")
    parser.add_argument("--only", action="append", default=[], metavar="NAME",
                        help="limit to 'template' or a month label such as 04/2026 (repeatable)")
    args = parser.parse_args(argv)

    chosen = [(n, sid) for n, sid in targets() if not args.only or n in args.only]
    unknown = set(args.only) - {n for n, _ in targets()}
    if unknown:
        out(f"unknown target(s): {', '.join(sorted(unknown))}")
        return 1

    out(("APPLY" if args.apply else "DRY RUN (nothing is written; add --apply)")
        + f": {len(chosen)} sheet(s)")
    bad = 0
    for name, sheet_id in chosen:
        try:
            result = patch_summary(open_summary(name, sheet_id), apply=args.apply)
        except Exception as exc:  # one unreachable sheet must not hide the others
            result = Result("error", f"{type(exc).__name__}: {exc}")
        if result.action in ("refused", "failed", "error"):
            bad += 1
        out(f"  {name:<9} {result.action:<13} {result.detail}")
    out(ROLLBACK)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:], service_account_opener()))
