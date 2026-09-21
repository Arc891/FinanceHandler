#!/usr/bin/env python3
"""
Privacy-safe shape report for the monthly budget spreadsheets and ASN CSV exports.

Prints structure only: tab names, header rows, row counts, date ranges, category
counts and which period-boundary markers (DUO / salary) are present on which dates.
It never prints amounts, descriptions, counterparty names or IBANs.

Usage:
    venv/bin/python scripts/sheet_shape.py sheets            # every sheet the service account can see
    venv/bin/python scripts/sheet_shape.py sheets "Maandelijks Budget 04/2026"
    venv/bin/python scripts/sheet_shape.py csv path/to/export.csv [more.csv ...]
"""

import csv
import os
import re
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

DATE_RE = re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$")
# Markers that start a financial month. Matched against counterparty + remittance,
# case-insensitive. Kept in sync with CATEGORIZATION_RULES_INCOME in constants.py.
BOUNDARY_MARKERS = {
    "DUO": re.compile(r"\bDUO\b", re.IGNORECASE),
    "SALARIS": re.compile(r"SALARIS", re.IGNORECASE),
}


def _sort_key(d: str) -> str:
    dd, mm, yyyy = d.split("-")
    return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"


def _date_span(dates):
    dates = [d for d in dates if DATE_RE.match(d)]
    if not dates:
        return None
    dates.sort(key=_sort_key)
    return dates[0], dates[-1], len(dates)


def report_csv(path: str) -> None:
    print(f"\n== CSV {os.path.basename(path)}")
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and len(row) >= 18 and row[0].strip():
                rows.append(row)
    if not rows:
        print("  no parseable rows")
        return
    dates = [r[0].strip() for r in rows]
    span = _date_span(dates)
    signs = Counter("expense" if r[10].strip().startswith("-") else "income" for r in rows)
    print(f"  rows: {len(rows)}  span: {span[0]} .. {span[1]}  ({signs['income']} income / {signs['expense']} expense)")
    per_month = Counter(_sort_key(d)[:7] for d in dates if DATE_RE.match(d))
    print("  rows per calendar month:", dict(sorted(per_month.items())))
    codes = Counter(f"{r[13].strip()} {r[14].strip()}".strip() for r in rows)
    print("  transaction codes:", dict(codes.most_common(8)))
    for name, rx in BOUNDARY_MARKERS.items():
        hits = sorted({r[0].strip() for r in rows
                       if rx.search(r[3]) or rx.search(r[17])}, key=_sort_key)
        # Only count incoming money as a boundary candidate
        hits_income = sorted({r[0].strip() for r in rows
                              if (rx.search(r[3]) or rx.search(r[17]))
                              and not r[10].strip().startswith("-")}, key=_sort_key)
        print(f"  marker {name}: on {len(hits)} row-dates, income on dates {hits_income}")


def report_sheet(sh, tab: str = "Transactions") -> None:
    print(f"\n== SHEET {sh.title}")
    meta = sh.fetch_sheet_metadata()
    for s in meta["sheets"]:
        p = s["properties"]
        gp = p.get("gridProperties", {})
        print(f"  tab {p['title']!r}: {gp.get('rowCount')}x{gp.get('columnCount')}")
    try:
        ws = sh.worksheet(tab)
    except Exception:
        print(f"  !! no {tab!r} tab")
        return
    header = ws.get("A1:L4")
    for i, row in enumerate(header, 1):
        # header rows carry no personal data; print them so layout drift is visible
        print(f"  header r{i}: {row}")
    values = ws.get("B5:J2000")
    exp_dates, inc_dates = [], []
    exp_cats, inc_cats = Counter(), Counter()
    last_exp_row = last_inc_row = None
    for i, row in enumerate(values, start=5):
        row = row + [""] * (9 - len(row))
        if row[0].strip():
            exp_dates.append(row[0].strip())
            exp_cats[row[3].strip() or "(blank)"] += 1
            last_exp_row = i
        if row[5].strip():
            inc_dates.append(row[5].strip())
            inc_cats[row[8].strip() or "(blank)"] += 1
            last_inc_row = i
    for label, dates, cats, last in (("expenses", exp_dates, exp_cats, last_exp_row),
                                     ("income", inc_dates, inc_cats, last_inc_row)):
        span = _date_span(dates)
        if span:
            print(f"  {label}: {len(dates)} rows, span {span[0]} .. {span[1]}, last row {last}, next free row {last + 1}")
            print(f"    categories: {dict(cats.most_common())}")
        else:
            print(f"  {label}: empty, next free row 5")


def main(argv):
    if len(argv) < 2 or argv[1] not in ("sheets", "csv"):
        print(__doc__)
        return 1
    if argv[1] == "csv":
        for path in argv[2:]:
            report_csv(path)
        return 0

    import gspread
    from google.oauth2.service_account import Credentials
    from config.config_settings import GOOGLE_CREDENTIALS_PATH, GSHEET_TAB

    creds = Credentials.from_service_account_file(
        os.path.join(PROJECT_ROOT, GOOGLE_CREDENTIALS_PATH),
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    wanted = argv[2:]
    files = gc.list_spreadsheet_files()
    print(f"service account sees {len(files)} spreadsheets:")
    for f in files:
        print(f"  - {f['name']}")
    for f in files:
        if wanted and f["name"] not in wanted:
            continue
        report_sheet(gc.open_by_key(f["id"]), GSHEET_TAB)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
