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
        self._tabs = {}
        for ws in (tabs or [FakeWorksheet("Transactions")]):
            self.add(ws)

    def add(self, ws):
        ws.spreadsheet = self
        self._tabs[ws.title] = ws
        return ws

    def worksheet(self, title):
        try:
            return self._tabs[title]
        except KeyError:
            raise gspread.exceptions.WorksheetNotFound(title) from None

    def worksheets(self):
        return list(self._tabs.values())

    @property
    def transactions(self):
        return self._tabs["Transactions"]


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
