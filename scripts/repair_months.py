#!/usr/bin/env python3
"""Inspect and repair the known 2026 monthly sheet layout defects.

Default is a structure-only dry run. No transaction rows or config settings are
read. The service-account key is loaded by Google's library without printing it.

    venv/bin/python scripts/repair_months.py
    venv/bin/python scripts/repair_months.py --apply   # only after owner approval

Targets: template and registered 01-10/2026. Repairs are confined to the
Summary cells B36 and J35, Summary formatting J35:K35, Transactions number
formats C5/H5, and Transactions validation rules on 07-10/2026. The script
checks every target before applying anything; Google writes are not atomic.
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from constants import ExpenseCategory, IncomeCategory  # noqa: E402
from finance_core.sheet_index import load_index  # noqa: E402
from finance_core.sheet_registry import validation_requests  # noqa: E402

TEMPLATE_ID = "1OSi4W3B3PrfCTQyxt3OreLmqSs4nXY82Wlg1_eohTs8"
INDEX_PATH = os.path.join(PROJECT_ROOT, "data", "sheet_index.json")
KEY_PATH = os.path.join(PROJECT_ROOT, "src", "config", "google_service_account.json")
CREATED_MONTHS = tuple(f"{n:02d}/2026" for n in range(7, 11))
INCOME_MONTHS = tuple(f"{n:02d}/2026" for n in range(1, 9))
ALL_MONTHS = tuple(f"{n:02d}/2026" for n in range(1, 11))


@dataclass(frozen=True)
class Target:
    name: str
    sheet_id: str


@dataclass(frozen=True)
class Action:
    target: Target
    kind: str
    location: str
    args: tuple = ()


class RequestPacer:
    """Keep an apply run below the Sheets quota shared by its reads and writes."""

    def __init__(self, interval=1.5, *, clock=time.monotonic, sleep=time.sleep):
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self.last = None

    def call(self, request):
        now = self.clock()
        if self.last is not None:
            delay = self.interval - (now - self.last)
            if delay > 0:
                self.sleep(delay)
                now = self.clock()
        self.last = now
        return request.execute()


def targets(index):
    missing = [name for name in ALL_MONTHS if name not in index]
    if missing:
        raise ValueError("missing registered month(s): " + ", ".join(missing))
    return [Target("template", TEMPLATE_ID)] + [Target(name, index[name]["id"]) for name in ALL_MONTHS]


def discover_missing(index, lookup_title):
    """Resolve local index gaps by exact Drive title, only in memory."""
    merged = dict(index)
    used = {entry["id"] for entry in merged.values()}
    for name in ALL_MONTHS:
        if name in merged:
            continue
        ids = lookup_title(f"Maandelijks Budget {name}")
        if len(ids) != 1 or ids[0] in used:
            raise ValueError(f"{name}: expected one unique spreadsheet by exact title")
        merged[name] = {"id": ids[0]}
        used.add(ids[0])
    return merged


def inspect_target(target, client):
    """Return actions, layout problems, and current template category mismatches."""
    actions, problems, mismatches = [], [], []
    name = target.name
    if name == "template" or name in CREATED_MONTHS:
        value = client.value(target, "B36")
        if value == "abonnementen":
            actions.append(Action(target, "label", "Summary!B36", ("B36", "Abonnementen")))
        elif value != "Abonnementen":
            problems.append("Summary!B36 has an unexpected label")

    if name == "template":
        for kind, a1, enum in (("expense", "B27:B45", ExpenseCategory),
                               ("income", "H27:H44", IncomeCategory)):
            labels = set(client.category_labels(target, a1))
            for category in enum:
                if category.value not in labels:
                    mismatches.append(f"{kind}: {category.value}")
                    if not (category.value == "Abonnementen" and kind == "expense"
                            and any(a.kind == "label" for a in actions)):
                        problems.append(f"template {kind} category missing: {category.value}")

    if name in INCOME_MONTHS:
        value = client.value(target, "J35")
        if value in ("", None):
            actions.append(Action(target, "zero", "Summary!J35", ("J35", 0)))
        elif value not in (0, 0.0, "0") or isinstance(value, bool):
            problems.append("Summary!J35 contains an unexpected value")
        source = [client.format(target, "Summary", cell) for cell in ("J34", "K34")]
        dest = [client.format(target, "Summary", cell) for cell in ("J35", "K35")]
        if any(not fmt for fmt in source):
            problems.append("Summary!J34:K34 has a missing source format")
        elif source != dest:
            actions.append(Action(target, "summary_format", "Summary!J35:K35",
                                  ("Summary", "J34:K34", "J35:K35")))

    if name in CREATED_MONTHS:
        for col in ("C", "H"):
            source_cell, dest_cell = f"{col}6", f"{col}5"
            source = client.format(target, "Transactions", source_cell).get("numberFormat")
            dest = client.format(target, "Transactions", dest_cell).get("numberFormat")
            if not source or source.get("type") != "CURRENCY":
                problems.append(f"Transactions!{source_cell} is not a CURRENCY source")
            elif source != dest:
                actions.append(Action(target, "currency_format", f"Transactions!{dest_cell}",
                                      ("Transactions", source_cell, dest_cell)))
        count = client.validation_count(target)
        if count < 1:
            problems.append("Transactions has no validation rules to rebind")
        else:
            actions.append(Action(target, "validations", f"Transactions validations ({count} ranges)"))
    return actions, problems, mismatches


def execute(client, action):
    if action.kind in ("label", "zero"):
        client.set_value(action.target, *action.args)
    elif action.kind in ("summary_format", "currency_format"):
        client.copy_format(action.target, *action.args, number_only=action.kind == "currency_format")
    elif action.kind == "validations":
        client.rebind_validations(action.target)
    else:
        raise AssertionError(action.kind)


def run(argv, client, index, out=print):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="apply the reviewed repairs")
    args = parser.parse_args(argv)
    try:
        chosen = targets(index)
    except ValueError as exc:
        out(f"refused: {exc}")
        return 1
    out(f"{'APPLY' if args.apply else 'DRY RUN (nothing written)'}: {len(chosen)} sheets")
    plans, bad = [], False
    for target in chosen:
        try:
            actions, problems, mismatches = inspect_target(target, client)
        except Exception as exc:
            actions, problems, mismatches = [], [f"inspection failed ({type(exc).__name__})"], []
        plans.extend(actions)
        out(f"  {target.name}: {len(actions)} planned operation(s)")
        for action in actions:
            out(f"    {action.location}: {action.kind}")
        for mismatch in mismatches:
            out(f"    template category mismatch: {mismatch}")
        for problem in problems:
            out(f"    REFUSED: {problem}")
        bad |= bool(problems)
    out(f"TOTAL: {len(plans)} planned operation(s), {sum(a.kind == 'validations' for a in plans)} validation rebind(s)")
    if bad:
        out("No writes: at least one target failed inspection.")
        return 1
    if not args.apply:
        return 0
    for action in plans:
        try:
            execute(client, action)
        except Exception as exc:
            out(f"FAILED {action.target.name} {action.location}: {type(exc).__name__}")
            out("Stopped after a partial apply; inspect again before retrying.")
            return 1
    out(f"Applied {len(plans)} operation(s). Run the dry run again to check remaining changes.")
    return 0


class LiveClient:
    """Metadata and Summary category reads; narrowly scoped Sheets writes."""

    def __init__(self, service, pacer=None):
        self.sheets = service.spreadsheets()
        self.pacer = pacer
        self._validation_cache = {}
        self._tab_cache = {}
        self._format_cache = {}

    def _execute(self, request):
        return self.pacer.call(request) if self.pacer else request.execute()

    def tab_id(self, target, tab):
        if target.sheet_id not in self._tab_cache:
            got = self.sheets.get(spreadsheetId=target.sheet_id,
                                  fields="sheets(properties(sheetId,title))")
            got = self._execute(got)
            self._tab_cache[target.sheet_id] = {
                s["properties"]["title"]: s["properties"]["sheetId"] for s in got["sheets"]}
        return self._tab_cache[target.sheet_id][tab]

    def value(self, target, cell):
        got = self.sheets.values().get(spreadsheetId=target.sheet_id, range=f"Summary!{cell}",
                                       valueRenderOption="FORMULA")
        got = self._execute(got)
        return (got.get("values") or [[""]])[0][0]

    def category_labels(self, target, a1):
        got = self.sheets.values().get(spreadsheetId=target.sheet_id,
                                       range=f"Summary!{a1}")
        got = self._execute(got)
        return [row[0] for row in got.get("values", []) if row]

    def format(self, target, tab, cell):
        key = target.sheet_id, tab
        if key not in self._format_cache:
            a1 = "J34:K35" if tab == "Summary" else "C5:H6"
            got = self.sheets.get(spreadsheetId=target.sheet_id, ranges=[f"{tab}!{a1}"],
                                  includeGridData=True,
                                  fields="sheets.data(startRow,startColumn,rowData(values(userEnteredFormat)))"
                                  )
            got = self._execute(got)
            cells = {}
            for sheet in got.get("sheets", []):
                for data in sheet.get("data", []):
                    r0, c0 = data.get("startRow", 0), data.get("startColumn", 0)
                    for i, row in enumerate(data.get("rowData", [])):
                        for j, value in enumerate(row.get("values", [])):
                            cells[(r0 + i, c0 + j)] = value.get("userEnteredFormat", {})
            self._format_cache[key] = cells
        col = ord(cell[0]) - 65
        row = int(cell[1:]) - 1
        return self._format_cache[key].get((row, col), {})

    def validation_count(self, target):
        tab_id = self.tab_id(target, "Transactions")
        got = self.sheets.get(spreadsheetId=target.sheet_id, includeGridData=True,
                              fields="sheets(properties(sheetId),data(startRow,startColumn,"
                                     "rowData(values(dataValidation))))")
        got = self._execute(got)
        requests = validation_requests(got, tab_id)
        for col in (4, 9):  # Transactions!E5 and J5, zero-based columns
            if not any((r["setDataValidation"]["range"]["startColumnIndex"] == col
                        and r["setDataValidation"]["range"]["startRowIndex"] <= 4
                        < r["setDataValidation"]["range"]["endRowIndex"]
                        and r["setDataValidation"]["rule"].get("condition", {}).get("type") == "ONE_OF_RANGE")
                       for r in requests):
                raise ValueError("missing category validation")
        self._validation_cache[target.sheet_id] = requests
        return len(requests)

    def set_value(self, target, cell, value):
        request = self.sheets.values().update(spreadsheetId=target.sheet_id,
                                              range=f"Summary!{cell}", valueInputOption="RAW",
                                              body={"values": [[value]]})
        self._execute(request)

    def copy_format(self, target, tab, source, destination, *, number_only=False):
        tab_id = self.tab_id(target, tab)
        if number_only:
            fmt = self.format(target, tab, source)["numberFormat"]
            col = ord(destination[0]) - ord("A")
            row = int(destination[1:]) - 1
            request = {"repeatCell": {"range": {"sheetId": tab_id, "startRowIndex": row,
                                                   "endRowIndex": row + 1, "startColumnIndex": col,
                                                   "endColumnIndex": col + 1},
                                      "cell": {"userEnteredFormat": {"numberFormat": fmt}},
                                      "fields": "userEnteredFormat.numberFormat"}}
        else:
            def grid(a1):
                first, last = a1.split(":")
                return {"sheetId": tab_id, "startRowIndex": int(first[1:]) - 1,
                        "endRowIndex": int(last[1:]), "startColumnIndex": ord(first[0]) - 65,
                        "endColumnIndex": ord(last[0]) - 64}
            request = {"copyPaste": {"source": grid(source), "destination": grid(destination),
                                     "pasteType": "PASTE_FORMAT"}}
        self._execute(self.sheets.batchUpdate(spreadsheetId=target.sheet_id,
                                             body={"requests": [request]}))

    def rebind_validations(self, target):
        requests = self._validation_cache[target.sheet_id]
        self._execute(self.sheets.batchUpdate(spreadsheetId=target.sheet_id,
                                             body={"requests": requests}))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--apply", action="store_true")
    known, _ = parser.parse_known_args(argv)
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    scope = "https://www.googleapis.com/auth/spreadsheets"
    if not known.apply:
        scope += ".readonly"
    try:
        index = load_index(INDEX_PATH)
        pacer = RequestPacer() if known.apply else None
        scopes = [scope]
        if any(name not in index for name in ALL_MONTHS):
            scopes.append("https://www.googleapis.com/auth/drive.readonly")
        creds = Credentials.from_service_account_file(KEY_PATH, scopes=scopes)
        if len(scopes) > 1:
            drive = build("drive", "v3", credentials=creds, cache_discovery=False).files()

            def lookup_title(title):
                query = ("name = '" + title.replace("'", "\\'") + "' and "
                         "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false")
                ids, token = [], None
                while True:
                    request = drive.list(q=query, spaces="drive", pageSize=100,
                                         fields="nextPageToken,files(id)", pageToken=token)
                    got = pacer.call(request) if pacer else request.execute()
                    ids.extend(item["id"] for item in got.get("files", []))
                    token = got.get("nextPageToken")
                    if not token:
                        return ids

            index = discover_missing(index, lookup_title)
        client = LiveClient(build("sheets", "v4", credentials=creds, cache_discovery=False), pacer)
        return run(argv, client, index)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 1
    except Exception as exc:
        print(f"repair unavailable: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
