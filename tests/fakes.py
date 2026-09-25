"""
In-memory stand-ins for the gspread objects the Google layer touches.

FakeWorksheet models what matters for the append contract (plan 4.5, 4.6):
  - values are stored natively: date serials as int, amounts as int/float, text as str;
  - ``get`` trims trailing empty cells and rows the way the Sheets API does, keeps
    internal blank rows as ``[]``, and renders numbers in the nl_NL display format
    unless UNFORMATTED_VALUE is requested (so a caller that forgets it cannot match);
  - ``update`` requires an explicit value_input_option. USER_ENTERED models the
    nl_NL parse: "DD-MM-YYYY" becomes a serial, "12,34" becomes 12.34, and "12.34"
    stays text ('.' is the thousands separator there). RAW stores values as given;
  - writing past ``row_count`` fails like the API's "exceeds grid limits";
  - ``update_faults`` injects failures before or after the mutation lands.
"""

import re
import threading
import time
from datetime import date

import gspread

EPOCH = date(1899, 12, 30)
_CELL_RE = re.compile(r"^([A-Z]+)(\d*)$")
_NL_NUMBER_RE = re.compile(r"^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_NL_DATE_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def serial(d: date) -> int:
    return (d - EPOCH).days


def parse_range(a1):
    if "!" in a1:
        a1 = a1.split("!", 1)[1]
    first, _, last = a1.partition(":")
    m1 = _CELL_RE.match(first)
    c1, r1 = col_index(m1.group(1)), int(m1.group(2) or 1)
    if not last:
        return c1, r1, c1, r1
    m2 = _CELL_RE.match(last)
    c2, r2 = col_index(m2.group(1)), (int(m2.group(2)) if m2.group(2) else None)
    return c1, r1, c2, r2


def _blank(v):
    return v is None or v == ""


def _render_nl(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return v
    whole, _, frac = f"{abs(v):.2f}".partition(".")
    whole = f"{int(whole):,}".replace(",", ".")
    return f"{'-' if v < 0 else ''}{whole},{frac}"


def user_entered(v):
    if isinstance(v, str):
        if v == "":
            return None
        if v.startswith("'"):
            return v[1:]
        m = _NL_DATE_RE.match(v)
        if m:
            return serial(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        if _NL_NUMBER_RE.match(v):
            return float(v.replace(".", "").replace(",", "."))
        return v
    return v


def raw(v):
    return None if v == "" else v


class FakeWorksheet:
    def __init__(self, title="Transactions", rows=77, cols=11):
        self.title = title
        self._rows = rows
        self.col_count = cols
        self.cells = {}
        self.calls = []            # ("update", range, option, values) / ("resize", rows) / ("get", range, option)
        self.update_faults = []    # [("before"|"after", exception), ...], consumed per update
        self.get_delay = 0.0
        self.spreadsheet = None
        self.id = None
        self.validations = {}      # "E5" -> {"type": ..., "values": [...]}
        self._mutex = threading.Lock()

    # gspread surface ------------------------------------------------------
    @property
    def row_count(self):
        return self._rows

    def get(self, range_name=None, value_render_option=None, **kwargs):
        if self.get_delay:
            time.sleep(self.get_delay)
        self.calls.append(("get", range_name, str(value_render_option)))
        c1, r1, c2, r2 = parse_range(range_name)
        r2 = self._rows if r2 is None else r2
        unformatted = str(value_render_option) == "UNFORMATTED_VALUE"
        out = []
        for r in range(r1, r2 + 1):
            row = []
            for c in range(c1, c2 + 1):
                v = self.cells.get((r, c))
                if callable(v):
                    v = v()
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                row.append("" if v is None else (v if unformatted else _render_nl(v)))
            while row and _blank(row[-1]):
                row.pop()
            out.append(row)
        while out and not out[-1]:
            out.pop()
        return out

    def update(self, values=None, range_name=None, value_input_option=None, **kwargs):
        assert value_input_option is not None, "value_input_option must be explicit"
        option = str(value_input_option)
        fault = self.update_faults.pop(0) if self.update_faults else None
        if fault and fault[0] == "before":
            raise fault[1]
        c1, r1, c2, r2 = parse_range(range_name)
        if r1 + len(values) - 1 > self._rows:
            raise ValueError(f"Range {range_name} exceeds grid limits ({self._rows} rows)")
        convert = user_entered if option == "USER_ENTERED" else raw
        with self._mutex:
            for i, row in enumerate(values):
                for j, v in enumerate(row):
                    self.cells[(r1 + i, c1 + j)] = convert(v)
        self.calls.append(("update", range_name, option, [list(r) for r in values]))
        if fault and fault[0] == "after":
            raise fault[1]
        return {"updatedRange": range_name}

    def get_all_values(self, **kwargs):
        last_col = chr(64 + min(self.col_count, 26))
        return self.get(f"A1:{last_col}{self._rows}")

    def resize(self, rows=None, cols=None):
        self.calls.append(("resize", rows))
        if rows is not None:
            self._rows = rows
        if cols is not None:
            self.col_count = cols

    def batch_clear(self, ranges):
        for rng in ranges:
            c1, r1, c2, r2 = parse_range(rng)
            for r in range(r1, (r2 or self._rows) + 1):
                for c in range(c1, c2 + 1):
                    self.cells.pop((r, c), None)

    # test helpers -----------------------------------------------------------
    def put(self, top_left, rows):
        c1, r1, _, _ = parse_range(top_left)
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                self.cells[(r1 + i, c1 + j)] = None if v == "" else v

    def rows(self, first_col, last_col, start=5):
        """Native values of a column range from ``start`` to its last non-empty row."""
        c1, c2 = col_index(first_col), col_index(last_col)
        last = max([r for (r, c), v in self.cells.items() if c1 <= c <= c2 and not _blank(v)],
                   default=start - 1)
        return [[self.cells.get((r, c)) for c in range(c1, c2 + 1)] for r in range(start, last + 1)]

    def updates(self):
        return [c for c in self.calls if c[0] == "update"]


class FakeSpreadsheet:
    def __init__(self, sheet_id="sheet-1", title="Maandelijks Budget 07/2026", tabs=None):
        self.id = sheet_id
        self.title = title
        self.tabs = []
        for ws in (tabs if tabs is not None else [FakeWorksheet("Transactions")]):
            self.add(ws)

    def add(self, ws):
        ws.spreadsheet = self
        if getattr(ws, "id", None) is None:
            ws.id = 100 + len(self.tabs)
        self.tabs.append(ws)
        return ws

    def worksheet(self, title):
        for ws in self.tabs:
            if ws.title == title:
                return ws
        raise gspread.exceptions.WorksheetNotFound(title)

    def worksheets(self):
        return list(self.tabs)

    def tab_by_id(self, tab_id):
        return next(ws for ws in self.tabs if ws.id == tab_id)

    @property
    def transactions(self):
        return self.worksheet("Transactions")


def expense_tx(date_str="24-06-2026", amount="-12.34", name="Picnic", rem="order 1",
               seq="1", description="Boodschappen Picnic", category="Boodschappen"):
    return {
        "booking_date": date_str,
        "transaction_amount": {"amount": amount, "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "debtor": {"name": name},
        "creditor": {"name": ""},
        "remittance_information": [rem] if rem else [],
        "bank_sequence_no": seq,
        "description": description,
        "category": category,
    }


def income_tx(date_str="24-06-2026", amount="314.10", name="DUO Hoofdrekening", rem="Studiefinanciering",
              seq="2", description="Duo uitkering", category="DUO"):
    tx = expense_tx(date_str, amount, name, rem, seq, description, category)
    tx.update({"credit_debit_indicator": "CRDT", "debtor": {"name": ""}, "creditor": {"name": name}})
    return tx


# ── a month workbook and the Drive/Sheets adapter ────────────────────────────

PLACEHOLDER = "! Nog in te delen !"
HEADERS = ["Date", "Amount", "Description", "Category"]
EXPENSE_CATEGORIES = ["Boodschappen", "Uit eten", "Abonnementen", "Vaste lasten"] + [PLACEHOLDER]
INCOME_CATEGORIES = ["DUO", "Salaris", "Persoonlijke rekening"]
_COL = {c: col_index(c) for c in "BCDEGHIJKL"}


def make_transactions(rows=77):
    ws = FakeWorksheet("Transactions", rows=rows)
    ws.put("B4", [HEADERS + [""] + HEADERS])
    ws.validations = {"E5": {"type": "ONE_OF_RANGE", "values": ["=Summary!$B$27:$C"]},
                      "J5": {"type": "ONE_OF_RANGE", "values": ["=Summary!$H$27:$I$44"]}}
    return ws


def make_summary(spreadsheet, *, income_bound=44, income_placeholder=True):
    """
    Summary tab whose totals are live over ``spreadsheet``'s Transactions tab.

    E26 sums expense amounts whose category is in the (open-ended) expense table,
    K26 sums income amounts whose category is in H28:H<income_bound>; the income
    placeholder sits at H35. E17 = L8 + K26 - E26. With no Transactions tab every
    formula reads #REF!, as a Summary copied before its Transactions would.
    """
    ws = FakeWorksheet("Summary", rows=60, cols=12)
    ws.put("B28", [[c] for c in EXPENSE_CATEGORIES])
    ws.put("H28", [[c] for c in INCOME_CATEGORIES])
    if income_placeholder:
        ws.put("H35", [[PLACEHOLDER]])

    def table(col, first, last):
        return {ws.cells.get((r, _COL[col])) for r in range(first, last + 1)} - {None}

    def total(amount_col, cat_col, cats):
        def f():
            try:
                tx = spreadsheet.worksheet("Transactions")
            except gspread.exceptions.WorksheetNotFound:
                return "#REF!"
            s = 0.0
            for (r, c), v in list(tx.cells.items()):
                if c == _COL[cat_col] and r >= 5 and v in cats():
                    amt = tx.cells.get((r, _COL[amount_col]))
                    s += amt if isinstance(amt, (int, float)) else 0
            return round(s, 2)
        return f

    e26 = total("C", "E", lambda: table("B", 28, 60))
    k26 = total("H", "J", lambda: table("H", 28, income_bound))

    def d17():
        v = ws.cells.get((8, _COL["L"]))
        return v if isinstance(v, (int, float)) else 0

    def e17():
        e, k = e26(), k26()
        if "#REF!" in (e, k):
            return "#REF!"
        return round(d17() + k - e, 2)

    ws.cells[(26, _COL["E"])] = e26
    ws.cells[(26, _COL["K"])] = k26
    ws.cells[(17, _COL["D"])] = d17
    ws.cells[(17, _COL["E"])] = e17
    return ws


def make_month(sheet_id, label, *, rows=0, l8=None, **summary_kw):
    """A registered month workbook with ``rows`` expense rows."""
    sh = FakeSpreadsheet(sheet_id, f"Maandelijks Budget {label}", tabs=[])
    sh.add(make_summary(sh, **summary_kw))
    sh.add(make_transactions())
    if rows:
        sh.transactions.put("B5", [[serial(date(2026, 6, 1 + i)), 10.0, f"r{i}", "Boodschappen"]
                                   for i in range(rows)])
    if l8 is not None:
        sh.worksheet("Summary").put("L8", [[l8]])
    return sh


class FakeHttpError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")

        class R:
            pass
        self.resp = R()
        self.resp.status = status


class FakeWorkbooks:
    """Stands in for sheet_registry.GoogleWorkbooks; ``log`` records every call in order."""

    TEMPLATE_ID = "template"
    FOLDER_ID = "folder"
    PROPS = {"locale": "nl_NL", "timeZone": "Europe/Monaco", "autoRecalc": "ON_CHANGE"}

    def __init__(self, *, summary_kw=None, folder_writable=True):
        self.books = {}
        self.props = {}
        self.parent = {}
        self.trashed = set()
        self.log = []
        self.faults = {}
        self.summary_kw = summary_kw or {}
        self.folder_writable = folder_writable
        self.copy_validations = True
        self.extra_copy = False
        self._n = 0
        template = FakeSpreadsheet(self.TEMPLATE_ID, "Template Maandelijks Budget xx/2026", tabs=[])
        template.add(make_summary(template))
        template.add(make_transactions())
        self.add_book(template)

    def add_book(self, sh, props=None, parents=(FOLDER_ID,)):
        self.books[sh.id] = sh
        self.props[sh.id] = dict(props or self.PROPS)
        self.parent[sh.id] = list(parents)
        return sh

    def _call(self, op, *args):
        self.log.append((op,) + args)
        pending = self.faults.get(op)
        if pending:
            raise pending.pop(0)

    # adapter surface --------------------------------------------------------
    def open(self, sheet_id):
        self._call("open", sheet_id)
        if sheet_id not in self.books or sheet_id in self.trashed:
            raise gspread.exceptions.SpreadsheetNotFound(sheet_id)
        return self.books[sheet_id]

    def properties(self, sheet_id):
        self._call("properties", sheet_id)
        sh = self.books[sheet_id]
        return dict(self.props[sheet_id], title=sh.title, tabs={ws.title: ws.id for ws in sh.tabs})

    def create_workbook(self, title, locale, time_zone, auto_recalc):
        self._call("create_workbook", title, locale, time_zone, auto_recalc)
        self._n += 1
        sh = FakeSpreadsheet(f"new-{self._n}", title, tabs=[FakeWorksheet("Sheet1", rows=1000, cols=26)])
        self.add_book(sh, {"locale": locale, "timeZone": time_zone, "autoRecalc": auto_recalc},
                      parents=("root",))
        return sh.id, sh.tabs[0].id

    def copy_tab(self, src_id, tab_id, dst_id):
        self._call("copy_tab", src_id, tab_id, dst_id)
        src = self.books[src_id].tab_by_id(tab_id)
        dst = self.books[dst_id]
        if src.title == "Summary":
            ws = make_summary(dst, **self.summary_kw)
        else:
            ws = FakeWorksheet(src.title, rows=src.row_count, cols=src.col_count)
            ws.cells = {k: v for k, v in src.cells.items()}
            ws.validations = dict(src.validations) if self.copy_validations else {}
        ws.title = f"Copy of {src.title}"
        ws.id = None
        dst.add(ws)
        if self.extra_copy:
            self.extra_copy = False
            dup = FakeWorksheet(f"Copy of {src.title} 2")
            dst.add(dup)
        return ws.id

    def rename_tab(self, sheet_id, tab_id, title):
        self._call("rename_tab", sheet_id, tab_id, title)
        self.books[sheet_id].tab_by_id(tab_id).title = title

    def delete_tab(self, sheet_id, tab_id):
        self._call("delete_tab", sheet_id, tab_id)
        sh = self.books[sheet_id]
        sh.tabs.remove(sh.tab_by_id(tab_id))

    def move_tab(self, sheet_id, tab_id, index):
        self._call("move_tab", sheet_id, tab_id, index)
        sh = self.books[sheet_id]
        ws = sh.tab_by_id(tab_id)
        sh.tabs.remove(ws)
        sh.tabs.insert(index, ws)

    def parents(self, sheet_id):
        self._call("parents", sheet_id)
        return list(self.parent[sheet_id])

    def move_to_folder(self, sheet_id, folder_id):
        self._call("move_to_folder", sheet_id, folder_id)
        if not self.folder_writable:
            return False
        self.parent[sheet_id] = [folder_id]
        return True

    def delete_file(self, sheet_id):
        self._call("delete_file", sheet_id)
        self.books.pop(sheet_id)

    def trash_file(self, sheet_id):
        self._call("trash_file", sheet_id)
        self.trashed.add(sheet_id)

    def validation(self, sheet_id, a1):
        self._call("validation", sheet_id, a1)
        tab, cell = a1.split("!")
        return self.books[sheet_id].worksheet(tab).validations.get(cell)

    # helpers ----------------------------------------------------------------
    def ops(self, *names):
        return [entry for entry in self.log if entry[0] in names]

    def created_ids(self):
        return [sid for sid in self.books if sid.startswith("new-")]
