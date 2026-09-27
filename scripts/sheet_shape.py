#!/usr/bin/env python3
"""
Privacy-safe shape report for the monthly budget spreadsheets and ASN CSV exports.

Prints structure only: tab names, header rows, row counts, date ranges, category
counts and which period-boundary markers (DUO / salary) are present on which dates.
It never prints amounts, descriptions, counterparty names or IBANs.

`--folder ID` prints the Drive tree under a folder instead: folder names,
spreadsheet names and ids, and whether the account can edit each. `--summary`
prints each sheet's Summary tab as formulas (numbers and texts inside a
formula masked), the category labels of its two tables and whether the
starting balance L8 is filled; never a rendered value.

It reads with the service account (read-only scopes), from `--credentials`
or src/config/google_service_account.json; the bot itself uses OAuth.

Usage:
    venv/bin/python scripts/sheet_shape.py sheets            # every sheet the service account can see
    venv/bin/python scripts/sheet_shape.py sheets "Maandelijks Budget 04/2026"
    venv/bin/python scripts/sheet_shape.py sheets --summary "Maandelijks Budget 04/2026"
    venv/bin/python scripts/sheet_shape.py sheets --folder <folder id>
    venv/bin/python scripts/sheet_shape.py csv path/to/export.csv [more.csv ...]
"""

import argparse
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
DEFAULT_KEY = os.path.join(PROJECT_ROOT, "src", "config", "google_service_account.json")
SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.readonly")
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
SUMMARY_RANGE = "Summary!A1:L60"
# The category tables on Summary: expenses (open-ended validation from B27)
# and income (validation bounded at row 44).
LABEL_TABLES = (("expense categories", "B", 27, 45), ("income categories", "H", 27, 44))
# Inside a formula: a number that is not part of a cell reference, and a
# non-empty text. 0 and 1 are left, as logic rather than amounts.
FORMULA_NUMBER = re.compile(r"(?<![A-Za-z$\d.,_])\d+(?:[.,]\d+)?(?![\d(])")
FORMULA_TEXT = re.compile(r'"[^"]+"')
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
            print(f"  {label}: {len(dates)} rows, span {span[0]} .. {span[1]}, last row {last}, "
                  f"next free row {last + 1}")
            print(f"    categories: {dict(cats.most_common())}")
        else:
            print(f"  {label}: empty, next free row 5")


# ── the Drive tree ──────────────────────────────────────────────────────────

def list_children(request, folder_id):
    """Every file directly in `folder_id`; `request(params)` is one files.list call."""
    params = {"q": f"'{folder_id}' in parents and trashed = false", "pageSize": 1000,
              "fields": "nextPageToken, files(id, name, mimeType, capabilities/canEdit)",
              "supportsAllDrives": True, "includeItemsFromAllDrives": True}
    files, token = [], None
    while True:
        page = request({**params, "pageToken": token} if token else params)
        files += page.get("files", [])
        token = page.get("nextPageToken")
        if not token:
            return files


def folder_tree(children_of, folder_id, name, seen=None):
    """{name, folders, sheets, others} under `folder_id`; a folder seen before is skipped."""
    seen = set() if seen is None else seen
    seen.add(folder_id)
    node = dict(name=name, folders=[], sheets=[], others=[])
    for f in sorted(children_of(folder_id), key=lambda f: f["name"].lower()):
        if f["mimeType"] == FOLDER_MIME:
            if f["id"] not in seen:
                node["folders"].append(folder_tree(children_of, f["id"], f["name"], seen))
        elif f["mimeType"] == SHEET_MIME:
            node["sheets"].append((f["name"], f["id"], f.get("capabilities", {}).get("canEdit", False)))
        else:
            node["others"].append(f["name"])
    return node


def format_tree(tree):
    counts = [0, 0, 0]

    def walk(node, depth):
        pad = "  " * depth
        counts[0] += 1
        lines = [f"{pad}{node['name']}/"]
        for sub in node["folders"]:
            lines += walk(sub, depth + 1)
        for name, fid, edit in node["sheets"]:
            counts[1] += 1
            lines.append(f"{pad}  {name}  {fid}  {'can edit' if edit else 'read only'}")
        for name in node["others"]:
            counts[2] += 1
            lines.append(f"{pad}  {name}  (not a spreadsheet)")
        return lines
    lines = walk(tree, 0)
    folders, sheets, others = counts
    lines.append(f"{folders} folders, {sheets} spreadsheets, {others} other file{'' if others == 1 else 's'}")
    return lines


# ── the Summary tab: formulas only ──────────────────────────────────────────

def mask_formula(formula):
    formula = FORMULA_TEXT.sub('"…"', formula)
    return FORMULA_NUMBER.sub(lambda m: m[0] if m[0] in ("0", "1") else "#", formula)


def _cell(col, row):
    return f"{chr(ord('A') + col)}{row}"


def _row_template(formula, row):
    """The formula with references to its own row written `{r}`."""
    return re.sub(rf"(?<![A-Za-z$])(\$?[A-Z]{{1,2}}\$?){row}(?!\d)", r"\g<1>{r}", formula)


def _formula_runs(grid):
    """Per column, consecutive rows whose formulas differ only in their own row: one line each run."""
    width = max((len(cells) for cells in grid), default=0)
    lines = []
    for c in range(width):
        run = []                                     # [(row, masked formula, template)]
        for r in range(1, len(grid) + 2):
            cells = grid[r - 1] if r <= len(grid) else []
            value = cells[c] if c < len(cells) else ""
            formula = mask_formula(value) if isinstance(value, str) and value.startswith("=") else None
            template = _row_template(formula, r) if formula else None
            if run and (template is None or template != run[-1][2] or r != run[-1][0] + 1):
                first, last = run[0], run[-1]
                if len(run) == 1:
                    lines.append(f"  {_cell(c, first[0])}: {first[1]}")
                else:
                    lines.append(f"  {_cell(c, first[0])}:{_cell(c, last[0])}: {first[2]}")
                run = []
            if template is not None:
                run.append((r, formula, template))
    return lines


def summary_lines(sh):
    props = sh.fetch_sheet_metadata().get("properties", {})
    lines = [f"== SUMMARY {sh.title}",
             f"  locale {props.get('locale')}, time zone {props.get('timeZone')}, "
             f"recalculation {props.get('autoRecalc')}"]
    grid = sh.values_get(SUMMARY_RANGE, params={"valueRenderOption": "FORMULA"}).get("values", [])

    def at(col, row):
        cells = grid[row - 1] if row - 1 < len(grid) else []
        return str(cells[col]) if col < len(cells) else ""

    lines += _formula_runs(grid)
    for title, letter, first, last in LABEL_TABLES:
        col = ord(letter) - ord("A")
        labels = [(at(col, r).strip(), f"{letter}{r}") for r in range(first, last + 1)
                  if at(col, r).strip() and not at(col, r).startswith("=")]
        if labels:
            n = len(labels)
            lines.append(f"  {title} {letter}{first}:{letter}{last}: {n} label{'' if n == 1 else 's'}, "
                         f"first {labels[0][0]} ({labels[0][1]}), last {labels[-1][0]} ({labels[-1][1]})")
        else:
            lines.append(f"  {title} {letter}{first}:{letter}{last}: no labels")
    lines.append(f"  L8 (starting balance): {'filled' if at(11, 8).strip() else 'empty'}")
    return lines


# ── entry point ─────────────────────────────────────────────────────────────

def service_account_client(path):
    import gspread
    from google.oauth2.service_account import Credentials
    if not os.path.exists(path):
        raise SystemExit(f"service account key not found at {path}; pass --credentials")
    return gspread.authorize(Credentials.from_service_account_file(path, scopes=list(SCOPES)))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("mode", choices=("sheets", "csv"))
    parser.add_argument("names", nargs="*", help="sheet names (sheets) or export paths (csv)")
    parser.add_argument("--credentials", default=DEFAULT_KEY, help="service account key file")
    parser.add_argument("--tab", default="Transactions")
    parser.add_argument("--folder", metavar="ID", help="print the Drive tree under this folder")
    parser.add_argument("--summary", action="store_true", help="print the Summary formulas")
    args = parser.parse_intermixed_args(argv)
    if args.mode == "csv":
        for path in args.names:
            report_csv(path)
        return 0

    gc = service_account_client(args.credentials)
    if args.folder:
        def request(params):
            return gc.http_client.request("get", DRIVE_FILES, params=params).json()
        name = gc.get_file_drive_metadata(args.folder).get("name", args.folder)
        for line in format_tree(folder_tree(lambda fid: list_children(request, fid), args.folder, name)):
            print(line)
        return 0
    files = gc.list_spreadsheet_files()
    print(f"service account sees {len(files)} spreadsheets:")
    for f in files:
        print(f"  - {f['name']}")
    for f in files:
        if args.names and f["name"] not in args.names:
            continue
        sh = gc.open_by_key(f["id"])
        if args.summary:
            print()
            for line in summary_lines(sh):
                print(line)
        else:
            report_sheet(sh, args.tab)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
