"""
Month -> spreadsheet resolution, and creating a month from the template (plan 4.4).

Two operations, named so they cannot drift into each other: ``resolve`` may
create, ``lookup`` never does. ``lookup`` is for information (the previous
month's closing balance); ``resolve`` is for a write target.

The bot has no Drive listing scope, so data/sheet_index.json (sheet_index.py)
is authoritative. A month is created only when the index misses, auto-create
is on, and the label is the month after the chronologically newest indexed
one (the adjacency guard). A created month passes a fidelity check, including
a behavioural totals check, before anything is written to the index.

``GoogleWorkbooks`` is the thin adapter over gspread and the Sheets/Drive
APIs; the registry depends only on its methods, which is what the tests fake.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import gspread
from gspread.utils import ValueInputOption, ValueRenderOption

from finance_core.config_access import project_path, setting
from finance_core.google_auth import GoogleAuthError
from finance_core.google_retry import status_of, with_retry
from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.sheet_index import (extract_spreadsheet_id, label_sort_key, load_index, newest,
                                      next_label, parse_label, previous_label, register, save_index)
from finance_core.sheet_writer import TRANSACTIONS_TAB, read_block

logger = logging.getLogger(__name__)

SUMMARY_TAB = "Summary"
HEADER = ["Date", "Amount", "Description", "Category"]
PLACEHOLDER = "! Nog in te delen !"     # ExpenseCategory.NOG_IN_TEDELEN and IncomeCategory.NOG_IN_TEDELEN
FIDELITY_AMOUNT = 12.34
TOLERANCE = 0.005
COPIED_PROPERTIES = ("locale", "timeZone", "autoRecalc")

PeriodStatus = Callable[[str], Optional[str]]


class SheetRegistryError(RuntimeError):
    pass


class MissingSheetError(SheetRegistryError):
    """No sheet for the label, and the bot may not create one."""


class StaleSheetError(SheetRegistryError):
    """The index names a spreadsheet that no longer opens (deleted or trashed)."""


class SheetLayoutError(SheetRegistryError):
    """A sheet does not have the monthly layout, or a created month failed its fidelity check."""


@dataclass(frozen=True)
class RegistryConfig:
    index_path: str
    template_id: str
    folder_id: Optional[str] = None
    name_pattern: str = "Maandelijks Budget {label}"
    auto_create: bool = True
    create_nonadjacent: bool = False

    @classmethod
    def from_settings(cls) -> "RegistryConfig":
        return cls(
            index_path=project_path(setting("SHEET_INDEX_PATH", "data/sheet_index.json")),
            template_id=setting("GSHEET_TEMPLATE_ID", "1OSi4W3B3PrfCTQyxt3OreLmqSs4nXY82Wlg1_eohTs8"),
            folder_id=setting("GSHEET_FOLDER_ID", "1QoYs19vu04_DFIszlfWOJP7BoQLEtfaG"),
            name_pattern=setting("GSHEET_NAME_PATTERN", "Maandelijks Budget {label}"),
            auto_create=bool(setting("GSHEET_AUTO_CREATE", True)),
            create_nonadjacent=bool(setting("GSHEET_CREATE_NONADJACENT", False)),
        )


@dataclass
class Resolved:
    label: str
    spreadsheet: object
    created: bool = False
    left_in_root: bool = False
    needs_starting_balance: bool = False

    def notes(self) -> list:
        """Lines for the run summary: what the user has to do by hand."""
        out = []
        if self.left_in_root:
            out.append(f"{self.label}: the new sheet is in My Drive root; move it into Financiën "
                       "(its id does not change)")
        if self.needs_starting_balance:
            out.append(f"{self.label}: set the starting balance in Summary!L8 by hand")
        return out


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if v is None or v == "":
        return 0.0
    return None


class SheetRegistry:
    def __init__(self, workbooks, config: RegistryConfig, *, retry=with_retry, now=None):
        self.wb = workbooks
        self.config = config
        self._retry = retry
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self._lock = threading.RLock()

    # ── public ────────────────────────────────────────────────────────────
    def lookup(self, label: str):
        """The indexed, verified spreadsheet for ``label``, or None. Never creates."""
        entry = load_index(self.config.index_path).get(label)
        return None if entry is None else self._open_verified(label, entry["id"])

    def resolve(self, label: str, *, upload_id: Optional[str] = None,
                period_status: Optional[PeriodStatus] = None) -> Resolved:
        """
        The write target for ``label``: an index hit, verified; or a month
        created from the template when the adjacency guard allows it.

        ``period_status(label)`` gives the current run's status for another
        period (None when this run does not touch it); it decides whether the
        previous month's closing balance may seed the new month's L8.
        """
        parse_label(label)
        with self._lock:
            index = load_index(self.config.index_path)
            entry = index.get(label)
            if entry:
                return Resolved(label, self._open_verified(label, entry["id"]))
            if not self.config.auto_create:
                raise MissingSheetError(
                    f"no sheet for {label} in the index and GSHEET_AUTO_CREATE is off; "
                    f"add it with /months register {label} <url>")
            self._check_adjacent(label, index)
            return self._create(label, upload_id, period_status)

    def register(self, label: str, url_or_id: str, *, force: bool = False) -> str:
        """Add a hand-made month to the index after verifying it. Returns sheet_index.register's status."""
        sheet_id = extract_spreadsheet_id(url_or_id)
        with self._lock:
            self._open_verified(label, sheet_id)
            index = load_index(self.config.index_path)
            status = register(index, label, sheet_id, force=force)
            save_index(self.config.index_path, index)
        return status

    def list_months(self) -> list:
        index = load_index(self.config.index_path)
        return [(label, index[label]) for label in sorted(index, key=label_sort_key)]

    # ── verification ──────────────────────────────────────────────────────
    def _open_verified(self, label, sheet_id):
        try:
            sh = self._retry(lambda: self.wb.open(sheet_id), what=f"open {label}")
        except gspread.exceptions.SpreadsheetNotFound as exc:
            raise StaleSheetError(
                f"the index maps {label} to {sheet_id}, which no longer opens (deleted or trashed?). "
                f"Restore it from the Drive bin, or re-point the label with /months register {label} <url>"
            ) from exc
        self._verify_layout(sh, label)
        return sh

    def _verify_layout(self, sh, label) -> None:
        expected = self.config.name_pattern.format(label=label)
        if sh.title != expected:
            raise SheetLayoutError(f"{label}: spreadsheet title is {sh.title!r}, expected {expected!r}")
        try:
            ws = self._retry(lambda: sh.worksheet(TRANSACTIONS_TAB), what="open Transactions")
        except gspread.exceptions.WorksheetNotFound as exc:
            raise SheetLayoutError(f"{label}: no {TRANSACTIONS_TAB} tab") from exc
        row = (self._retry(lambda: ws.get("B4:J4"), what="read header") or [[]])[0]
        row = [str(v).strip() for v in row] + [""] * (9 - len(row))
        if row[0:4] != HEADER or row[5:9] != HEADER:
            raise SheetLayoutError(f"{label}: {TRANSACTIONS_TAB} header row 4 is {row}, expected "
                                   f"{HEADER} in B:E and G:J")

    def _check_adjacent(self, label, index) -> None:
        top = newest(index)
        if top is None or label == next_label(top) or self.config.create_nonadjacent:
            return
        raise MissingSheetError(
            f"no sheet for {label}, and it is not the month after the newest indexed month {top}, "
            f"so the bot will not create it. If the sheet exists, add it with /months register {label} <url>; "
            "to fill a gap deliberately, set GSHEET_CREATE_NONADJACENT = True for that run")

    # ── create ────────────────────────────────────────────────────────────
    def _create(self, label, upload_id, period_status) -> Resolved:
        cfg, wb, retry = self.config, self.wb, self._retry
        title = cfg.name_pattern.format(label=label)
        tmpl = retry(lambda: wb.properties(cfg.template_id), what="read template")
        new_id, default_tab = retry(lambda: wb.create_workbook(
            title, tmpl["locale"], tmpl["timeZone"], tmpl["autoRecalc"]), what="create workbook")
        logger.info("Created workbook %s for %s", new_id, label)
        try:
            tab_ids = {}
            for tab in (TRANSACTIONS_TAB, SUMMARY_TAB):
                copied = retry(lambda: wb.copy_tab(cfg.template_id, tmpl["tabs"][tab], new_id),
                               what=f"copy {tab}")
                retry(lambda: wb.rename_tab(new_id, copied, tab), what=f"rename {tab}")
                tab_ids[tab] = copied
            retry(lambda: wb.delete_tab(new_id, default_tab), what="delete default tab")
            retry(lambda: wb.move_tab(new_id, tab_ids[SUMMARY_TAB], 0), what="reorder tabs")
            moved = bool(cfg.folder_id) and retry(lambda: wb.move_to_folder(new_id, cfg.folder_id),
                                                  what="move into folder")
            parents = retry(lambda: wb.parents(new_id), what="read parents")
            sh = retry(lambda: wb.open(new_id), what="open new workbook")
            self._fidelity_check(sh, new_id, tmpl, label)
        except BaseException:
            self._discard(new_id)
            raise
        left_in_root = bool(cfg.folder_id) and not moved
        if left_in_root:
            logger.warning("%s left in My Drive root (parents %s): drive.file cannot write the folder",
                           label, parents)

        seeded = self._seed_starting_balance(sh, label, period_status)

        with self._lock:
            index = load_index(cfg.index_path)
            register(index, label, new_id, created_by_bot=True, created_at=self._now(), upload_id=upload_id)
            save_index(cfg.index_path, index)
        return Resolved(label, sh, created=True, left_in_root=left_in_root, needs_starting_balance=not seeded)

    def _discard(self, sheet_id) -> None:
        try:
            self._retry(lambda: self.wb.delete_file(sheet_id), what="delete orphan")
            logger.warning("Deleted the half-created workbook %s", sheet_id)
        except Exception:
            logger.exception("Could not delete the half-created workbook %s; delete it by hand", sheet_id)

    def _fidelity_check(self, sh, sheet_id, tmpl, label) -> None:
        """Every assertion of plan 4.4 step 6; raise SheetLayoutError listing all that failed."""
        problems = []
        tabs = [ws.title for ws in sh.worksheets()]
        if tabs != [SUMMARY_TAB, TRANSACTIONS_TAB]:
            problems.append(f"tabs are {tabs}, expected {[SUMMARY_TAB, TRANSACTIONS_TAB]}")
        try:
            self._verify_layout(sh, label)
        except SheetLayoutError as exc:
            problems.append(str(exc))
        for cell in ("E5", "J5"):
            v = self._retry(lambda: self.wb.validation(sheet_id, f"{TRANSACTIONS_TAB}!{cell}"),
                            what=f"read validation {cell}")
            if (not v or v.get("type") != "ONE_OF_RANGE"
                    or any("#REF" in str(x) for x in v.get("values") or [])):
                problems.append(f"{TRANSACTIONS_TAB}!{cell} lacks the ONE_OF_RANGE category validation ({v})")
        props = self._retry(lambda: self.wb.properties(sheet_id), what="read new properties")
        for key in COPIED_PROPERTIES:
            if props.get(key) != tmpl.get(key):
                problems.append(f"{key} is {props.get(key)!r}, the template's is {tmpl.get(key)!r}")
        if not problems:
            problems += self._totals_check(sh, label)
        if problems:
            raise SheetLayoutError(f"created month {label} failed the fidelity check: " + "; ".join(problems))

    def _totals_check(self, sh, label) -> list:
        """
        Write one flagged expense and one flagged income row, assert E26, K26
        and E17 move by the amount and nothing reads #REF!, remove both, assert
        the totals return. Proves the placeholders reach the monthly totals.
        """
        summary = sh.worksheet(SUMMARY_TAB)
        tx_ws = sh.worksheet(TRANSACTIONS_TAB)
        problems = []

        def totals():
            out = {}
            for cell in ("E26", "K26", "E17"):
                got = self._retry(lambda: summary.get(cell, value_render_option=ValueRenderOption.unformatted),
                                  what=f"read {cell}")
                raw = got[0][0] if got and got[0] else ""
                out[cell] = _number(raw)
                if out[cell] is None:
                    problems.append(f"Summary!{cell} reads {raw!r}")
            return out

        def moved(before, after, cell, delta):
            ok = (before[cell] is not None and after[cell] is not None
                  and abs(after[cell] - before[cell] - delta) < TOLERANCE)
            if not ok:
                problems.append(f"Summary!{cell} went {before[cell]} -> {after[cell]}, expected {delta:+.2f}")

        year, month = parse_label(label)
        row = [f"01-{month:02d}-{year}", FIDELITY_AMOUNT, "fidelity check (removed automatically)", PLACEHOLDER]
        start = int(setting("GSHEET_DATA_START_ROW", 5))
        base = totals()
        try:
            tx_ws.update(values=[row], range_name=EXPENSES.a1(start, start),
                         value_input_option=ValueInputOption.user_entered)
            after_expense = totals()
            moved(base, after_expense, "E26", FIDELITY_AMOUNT)
            moved(base, after_expense, "E17", -FIDELITY_AMOUNT)
            tx_ws.update(values=[row], range_name=INCOME.a1(start, start),
                         value_input_option=ValueInputOption.user_entered)
            after_income = totals()
            moved(base, after_income, "K26", FIDELITY_AMOUNT)
            moved(after_expense, after_income, "E17", FIDELITY_AMOUNT)
            rendered = self._retry(lambda: summary.get_all_values(), what="scan Summary")
            if any("#REF!" in str(v) for r in rendered for v in r):
                problems.append("Summary contains #REF!")
        finally:
            blank = [["", "", "", ""]]
            tx_ws.update(values=blank, range_name=EXPENSES.a1(start, start), value_input_option=ValueInputOption.raw)
            tx_ws.update(values=blank, range_name=INCOME.a1(start, start), value_input_option=ValueInputOption.raw)
        restored = totals()
        for cell in ("E26", "K26", "E17"):
            moved(base, restored, cell, 0.0)
        if read_block(sh, EXPENSES).tuples or read_block(sh, INCOME).tuples:
            problems.append("the fidelity rows were not removed")
        return problems

    def _seed_starting_balance(self, sh, label, period_status) -> bool:
        """
        Step 7: copy the previous month's Summary!E17 into the new Summary!L8.

        Uses ``lookup``, never ``resolve``, so it cannot create the previous
        month. Only from a month that is `written` in this run or untouched by
        it: a half-written (`appending`) month yields a plausible, wrong balance.
        """
        prev = previous_label(label)
        status = period_status(prev) if period_status else None
        if status not in (None, "written"):
            logger.info("%s: previous month %s is %s; starting balance left for the user", label, prev, status)
            return False
        try:
            prev_sh = self.lookup(prev)
            if prev_sh is None:
                return False
            if not (read_block(prev_sh, EXPENSES).tuples or read_block(prev_sh, INCOME).tuples):
                return False
            got = self._retry(lambda: prev_sh.worksheet(SUMMARY_TAB).get(
                "E17", value_render_option=ValueRenderOption.unformatted), what="read previous E17")
            value = got[0][0] if got and got[0] else None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            sh.worksheet(SUMMARY_TAB).update(values=[[value]], range_name="L8",
                                             value_input_option=ValueInputOption.raw)
            return True
        except GoogleAuthError:
            raise
        except Exception:
            logger.exception("%s: could not seed the starting balance from %s", label, prev)
            return False


class GoogleWorkbooks:
    """The Google calls the registry makes, over gspread plus the Sheets and Drive v3 services."""

    def __init__(self, gspread_client, sheets_service, drive_service):
        self.gc = gspread_client
        self.sheets = sheets_service.spreadsheets()
        self.drive = drive_service.files()

    @classmethod
    def from_credentials(cls, credentials=None) -> "GoogleWorkbooks":
        from finance_core.google_auth import (get_credentials, get_drive_service, get_gspread_client,
                                              get_sheets_service)
        creds = credentials or get_credentials()
        return cls(get_gspread_client(creds), get_sheets_service(creds), get_drive_service(creds))

    def open(self, sheet_id):
        return self.gc.open_by_key(sheet_id)

    def properties(self, sheet_id) -> dict:
        got = self.sheets.get(spreadsheetId=sheet_id,
                              fields="properties(title,locale,timeZone,autoRecalc),sheets.properties(sheetId,title)"
                              ).execute()
        props = dict(got["properties"])
        props["tabs"] = {s["properties"]["title"]: s["properties"]["sheetId"] for s in got.get("sheets", [])}
        return props

    def create_workbook(self, title, locale, time_zone, auto_recalc):
        body = {"properties": {"title": title, "locale": locale, "timeZone": time_zone, "autoRecalc": auto_recalc}}
        got = self.sheets.create(body=body, fields="spreadsheetId,sheets.properties(sheetId)").execute()
        return got["spreadsheetId"], got["sheets"][0]["properties"]["sheetId"]

    def copy_tab(self, src_id, tab_id, dst_id):
        got = self.sheets.sheets().copyTo(spreadsheetId=src_id, sheetId=tab_id,
                                          body={"destinationSpreadsheetId": dst_id}).execute()
        return got["sheetId"]

    def _batch(self, sheet_id, request):
        self.sheets.batchUpdate(spreadsheetId=sheet_id, body={"requests": [request]}).execute()

    def rename_tab(self, sheet_id, tab_id, title):
        self._batch(sheet_id, {"updateSheetProperties": {
            "properties": {"sheetId": tab_id, "title": title}, "fields": "title"}})

    def delete_tab(self, sheet_id, tab_id):
        self._batch(sheet_id, {"deleteSheet": {"sheetId": tab_id}})

    def move_tab(self, sheet_id, tab_id, index):
        self._batch(sheet_id, {"updateSheetProperties": {
            "properties": {"sheetId": tab_id, "index": index}, "fields": "index"}})

    def parents(self, sheet_id) -> list:
        return self.drive.get(fileId=sheet_id, fields="parents").execute().get("parents", [])

    def move_to_folder(self, sheet_id, folder_id) -> bool:
        """False when drive.file gives no write access to the folder (403/404): the sheet stays in root."""
        current = ",".join(self.parents(sheet_id))
        try:
            self.drive.update(fileId=sheet_id, addParents=folder_id, removeParents=current,
                              fields="id,parents").execute()
            return True
        except Exception as exc:
            if status_of(exc) in (403, 404):
                logger.warning("Cannot move %s into folder %s: HTTP %s", sheet_id, folder_id, status_of(exc))
                return False
            raise

    def delete_file(self, sheet_id):
        self.drive.delete(fileId=sheet_id).execute()

    def trash_file(self, sheet_id):
        self.drive.update(fileId=sheet_id, body={"trashed": True}).execute()

    def validation(self, sheet_id, a1):
        got = self.sheets.get(spreadsheetId=sheet_id, ranges=[a1], includeGridData=True,
                              fields="sheets.data.rowData.values.dataValidation").execute()
        try:
            rule = got["sheets"][0]["data"][0]["rowData"][0]["values"][0]["dataValidation"]
        except (KeyError, IndexError):
            return None
        cond = rule.get("condition", {})
        return {"type": cond.get("type"),
                "values": [v.get("userEnteredValue") for v in cond.get("values", [])]}
