"""
Tests for scripts/eval_categoriser.py (plan section 6, the evaluation step).

Covers the layout detection, the multiset matching of export rows to sheet
rows, the mapping of old category names, the scores, and the privacy rules:
the report holds counts and category names only, log messages never reach
the terminal, and a crash prints no exception text. All data is synthetic.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

import eval_categoriser as ev
from fakes import expense_tx, income_tx

VALID = {"expenses": {"Boodschappen", "Dates/uitjes", "Abonnementen"},
         "income": {"Salaris", "Gift"}}
SECRET_NAME = "Jolanda Vermeulen"
SECRET_REM = "Tikkie etentje"


def raw(tx):
    return {k: v for k, v in tx.items() if k not in ("description", "category")}


def sheet_row(label="03/2024", block="expenses", date="2024-03-17",
              amount="47.35", category="Boodschappen", switched=False):
    return ev.SheetRow(label, block, date, amount, category, switched)


def res(category, method="ai_auto", confidence=0.9):
    return SimpleNamespace(category=category, method=method,
                           confidence=confidence)


# ── layout ──────────────────────────────────────────────────────────────────

def test_start_row_is_the_first_row_holding_a_date():
    values = [["Uitgaven"], [], ["Date", "Amount", "Description", "Category"],
              [45368, 12.5, "x", "Boodschappen"]]
    assert ev.detect_start_row(values) == 4


def test_start_row_accepts_text_dates():
    assert ev.detect_start_row([["Datum"], ["17-03-2024", "1"]]) == 2


def test_start_row_is_none_for_an_empty_block():
    assert ev.detect_start_row([["Date"], [], ["Totaal"]]) is None


def test_block_rows_read_serial_dates_and_absolute_amounts():
    values = [["Date"], [45368, 47.35, "desc", " Boodschappen "], [],
              ["", "", "", ""]]
    rows = ev.block_rows("03/2024", "expenses", values, 2)
    assert rows == [sheet_row(date="2024-03-17", amount="47.35")]


def test_negative_amount_marks_a_hand_switched_row():
    rows = ev.block_rows("03/2024", "expenses",
                         [["17-03-2024", -20, "d", "Gift"]], 1)
    assert rows[0].switched and rows[0].amount == "20.00"


# ── matching ────────────────────────────────────────────────────────────────

def test_row_matches_on_date_amount_and_block():
    tx = raw(expense_tx(date_str="17-03-2024", amount="-47.35"))
    m = ev.match_rows([tx], [sheet_row()], VALID, {})
    assert len(m.records) == 1
    assert m.records[0].label == "03/2024"
    assert m.truths[m.records[0].group] == ["Boodschappen"]


def test_row_found_only_in_the_other_block_is_not_scored():
    tx = raw(income_tx(date_str="17-03-2024", amount="47.35"))
    m = ev.match_rows([tx], [sheet_row(block="expenses", switched=True)],
                      VALID, {})
    assert m.records == [] and m.counts["other_block"] == 1


def test_matching_is_a_multiset():
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-47.35", seq=s))
           for s in ("1", "2")]
    m = ev.match_rows(txs, [sheet_row()], VALID, {})
    assert len(m.records) == 1 and m.counts["unmatched"] == 1


def test_old_category_names_are_mapped():
    tx = raw(expense_tx(date_str="17-03-2024", amount="-47.35"))
    m = ev.match_rows([tx], [sheet_row(category="Eten")], VALID,
                      {"Eten": "Boodschappen"})
    assert m.truths[m.records[0].group] == ["Boodschappen"]


def test_unmapped_and_undecided_rows_are_counted_not_scored():
    txs = [raw(expense_tx(date_str="17-03-2024", amount=a, seq=a))
           for a in ("-1.00", "-2.00", "-3.00")]
    rows = [sheet_row(amount="1.00", category="Oud"),
            sheet_row(amount="2.00", category="! Nog in te delen !"),
            sheet_row(amount="3.00", category="CACHED")]
    m = ev.match_rows(txs, rows, VALID, {})
    assert m.records == []
    assert m.counts["unmapped"] == 1 and m.counts["undecided"] == 2
    assert m.unmapped == {"Oud": 1}


# ── scoring ─────────────────────────────────────────────────────────────────

def records_for(truths, preds):
    """One group holding len(truths) rows with the given predictions."""
    group = ("03/2024", "2024-03-17", "5.00", "expenses")
    records = [ev.Record(i, None, "03/2024", group) for i in range(len(preds))]
    return records, {group: list(truths)}, [res(p) for p in preds]


def test_a_group_scores_as_a_multiset_intersection():
    records, truths, results = records_for(["A", "B"], ["B", "A"])
    rows = ev.score(records, truths, results)
    assert [r["correct"] for r in rows] == [True, True]
    records, truths, results = records_for(["A", "B"], ["A", "A"])
    rows = ev.score(records, truths, results)
    assert sorted(r["correct"] for r in rows) == [False, True]
    assert sorted(r["truth"] for r in rows) == ["A", "B"]


def scored(*rows):
    return [dict(truth=t, pred=p, method=m, confidence=c, correct=(t == p))
            for t, p, m, c in rows]


def test_report_bands_and_threshold_table():
    rows = scored(
        ("Boodschappen", "Boodschappen", "regex", 1.0),
        ("Boodschappen", "Boodschappen", "ai_auto", 0.9),
        ("Gift", "Salaris", "ai_auto", 0.9),
        ("Salaris", "Salaris", "ai_manual_needed", 0.6),
        ("Gift", "Boodschappen", "ai_manual_needed", 0.3),
        ("Gift", None, "none", 0.0),
    )
    rep = ev.build_report(rows)
    assert rep["overall"] == (6, 3)
    assert rep["methods"]["regex"] == (1, 1)
    assert rep["methods"]["ai"] == (4, 2)
    assert rep["methods"]["no answer"] == (1, 0)
    assert rep["bands"]["high"] == (2, 1)
    assert rep["bands"]["medium"] == (1, 1)
    assert rep["bands"]["low"] == (1, 0)
    t = {row["threshold"]: row for row in rep["thresholds"]}
    # 5 non-regex rows; at 0.9 the medium, low and no-answer rows are flagged
    assert (t[0.9]["flagged"], t[0.9]["written"], t[0.9]["written_ok"]) == (3, 2, 1)
    assert t[0.9]["attention"] == 4
    assert (t[0.6]["flagged"], t[0.6]["written_ok"], t[0.6]["attention"]) == (2, 2, 3)
    assert (t[0.0]["flagged"], t[0.0]["written"], t[0.0]["attention"]) == (1, 4, 3)
    assert rep["categories"]["Gift"] == (3, 0)
    assert dict(rep["confusions"])[("Gift", "Salaris")] == 1
    assert dict(rep["confusions"])[("Gift", None)] == 1


def test_disagreement_between_runs():
    assert ev.disagreement([["A", "B", "C", "D"], ["A", "X", "C", "D"]]) == (4, 1)
    assert ev.disagreement([["A"]]) == (1, 0)


# ── privacy ─────────────────────────────────────────────────────────────────

def test_report_holds_no_row_content():
    tx = raw(expense_tx(date_str="17-03-2024", amount="-47.35",
                        name=SECRET_NAME, rem=SECRET_REM))
    m = ev.match_rows([tx], [sheet_row()], VALID, {})
    rows = ev.score(m.records, m.truths, [res("Dates/uitjes", "ai_auto", 0.6)])
    text = "\n".join(ev.format_report(ev.build_report(rows), m, runs=[rows]))
    for secret in (SECRET_NAME, SECRET_REM, "47.35", "17-03", "2024-03-17"):
        assert secret not in text
    assert "Dates/uitjes" in text and "Boodschappen" in text


def test_only_repeated_unmapped_names_are_shown_and_truncated():
    unmapped = {"Oude categorie": 3, "eenmalig iets": 1, "x" * 80: 2}
    lines = ev.format_unmapped(unmapped)
    text = "\n".join(lines)
    assert "Oude categorie" in text and "eenmalig" not in text
    assert "x" * 41 not in text and "x" * 40 in text
    assert "1 row(s) under 1 name(s) used only once are not shown" in text


@pytest.fixture
def root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_log_messages_are_counted_never_printed(capsys, root_logger):
    counter = ev.install_quiet_logging()
    logging.getLogger("eval_test.anonymiser").warning(SECRET_NAME)
    logging.getLogger("finance_core.x").error("row %s", SECRET_REM)
    out = capsys.readouterr()
    assert SECRET_NAME not in out.out + out.err
    assert SECRET_REM not in out.out + out.err
    assert "1 warning(s), 1 error(s)" in "\n".join(counter.summary())


def test_log_records_are_bucketed_by_fixed_labels_only(root_logger):
    """The kinds of failure are counted; no message text is printed."""
    counter = ev.install_quiet_logging()
    cli = logging.getLogger("automation.claude_provider")
    cli.error("Claude Code CLI error: exit 1; subtype=error_max_turns; "
              f"terminal_reason=max_turns; result: {SECRET_NAME}")
    cli.error("Claude Code CLI error: exit 1; subtype=error_max_turns; "
              "terminal_reason=max_turns")
    cli.error("Claude Code CLI error: exit 1; stdout not JSON (812 bytes)")
    cli.error(f"Claude Code CLI error: exit 1; result: API Error: 529 "
              f"Overloaded {SECRET_REM}")
    cli.error("CLI completion failed: Claude Code CLI timed out. Run it.")
    cli.error(f"subtype=Jolanda {SECRET_NAME}")
    try:
        raise RuntimeError(SECRET_NAME)
    except RuntimeError:
        logging.getLogger("automation.ai_categorizer").error(
            f"Batch categorization chunk failed: {SECRET_NAME}", exc_info=True)
    logging.getLogger("automation.ai_categorizer").warning(
        "AI chunk call failed (RuntimeError); retrying once in 15s")
    text = "\n".join(counter.summary())
    assert ("automation.claude_provider ERROR [exit 1, subtype=error_max_turns, "
            "terminal_reason=max_turns]: 2") in text
    assert "[exit 1, stdout not JSON]: 1" in text
    assert "[exit 1, API 529, overloaded]: 1" in text
    assert "[timed out]: 1" in text
    assert "automation.claude_provider ERROR [other]: 1" in text
    assert "automation.ai_categorizer ERROR [RuntimeError]: 1" in text
    assert "automation.ai_categorizer WARNING [retry]: 1" in text
    for secret in (SECRET_NAME, "Jolanda", SECRET_REM, "812"):
        assert secret not in text


def test_a_crash_prints_the_type_and_place_only(capsys):
    def boom():
        raise ValueError(f"could not parse {SECRET_NAME}")
    code = ev.guarded(boom, debug=False)
    out = capsys.readouterr()
    assert code == 2
    assert "ValueError" in out.out and SECRET_NAME not in out.out + out.err


# ── the run ─────────────────────────────────────────────────────────────────

class FakeEngine:
    def __init__(self):
        self.calls = []

    async def batch_categorize(self, txs, **kwargs):
        self.calls.append(([tx["bank_sequence_no"] for tx in txs], kwargs))
        return [res("Boodschappen") for _ in txs]


def test_each_month_is_categorised_in_its_own_call():
    txs = [raw(expense_tx(date_str=d, amount="-1.00", seq=s))
           for d, s in (("17-03-2024", "1"), ("20-04-2024", "2"),
                        ("18-03-2024", "3"))]
    rows = [sheet_row(label="03/2024", date="2024-03-17", amount="1.00"),
            sheet_row(label="04/2024", date="2024-04-20", amount="1.00"),
            sheet_row(label="03/2024", date="2024-03-18", amount="1.00")]
    m = ev.match_rows(txs, rows, VALID, {})
    engine = FakeEngine()
    results = asyncio.run(ev.categorise(engine, m.records, parallel=2,
                                        say=lambda *_: None))
    assert [c[0] for c in engine.calls] == [["1", "3"], ["2"]]
    assert engine.calls[0][1] == {"max_parallel": 2}
    assert len(results) == 3 and all(r.category == "Boodschappen"
                                     for r in results)


def test_sheet_names_select_the_requested_years():
    files = [{"name": "Maandelijks Budget 03/2024", "id": "a"},
             {"name": "Maandelijks Budget 12/2025", "id": "b"},
             {"name": "Maandelijks Budget 01/2026", "id": "c"},
             {"name": "Iets anders", "id": "d"}]
    picked, ignored = ev.select_sheets(files, years={"2024", "2025"}, only=None)
    assert picked == [("03/2024", "a"), ("12/2025", "b")] and ignored == 2
    picked, _ = ev.select_sheets(files, years={"2024", "2025"},
                                 only={"12/2025"})
    assert picked == [("12/2025", "b")]


@pytest.mark.parametrize("arg, expected", [
    ("Eten=Boodschappen", ("Eten", "Boodschappen")),
    ("Auto / vervoer=Auto / vervoer / OV", ("Auto / vervoer", "Auto / vervoer / OV")),
])
def test_map_argument_splits_on_the_first_equals_sign(arg, expected):
    assert ev.parse_pair(arg) == expected


class FakeBook:
    """A spreadsheet answering one batchGet for both blocks of a tab."""

    def __init__(self, blocks, tab="Transactions"):
        self.blocks, self.tab, self.batch_calls = blocks, tab, 0

    def values_batch_get(self, ranges, params=None):
        self.batch_calls += 1
        assert params == {"valueRenderOption": "UNFORMATTED_VALUE"}
        out = []
        for r in ranges:
            tab, _, a1 = r.rpartition("!")
            if tab.strip("'") != self.tab:
                raise RateLimited(400)
            out.append({"range": r, "values": self.blocks[a1]} if self.blocks[a1]
                       else {"range": r})
        return {"valueRanges": out}

    def worksheets(self):
        return [SimpleNamespace(title=self.tab)]


class FakeGc:
    def __init__(self, books):
        self.books = books
        self.opened = {}

    def list_spreadsheet_files(self):
        return [{"name": f"Maandelijks Budget {label}", "id": label}
                for label in self.books]

    def open_by_key(self, key):
        book = self.books[key]
        if isinstance(book, dict):
            book = FakeBook(book)
        self.opened[key] = book
        return book


def test_dry_run_end_to_end_prints_structure_only(monkeypatch, capsys,
                                                  root_logger):
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-47.35",
                          name=SECRET_NAME, rem=SECRET_REM, seq="1")),
           raw(income_tx(date_str="18-03-2024", amount="1234.56",
                         name=SECRET_NAME, rem=SECRET_REM, seq="2"))]
    books = {"03/2024": {
        "B1:E": [["Date"], [], [], [45368, 47.35, SECRET_REM, "Eten"],
                 [45369, 9.99, SECRET_NAME, "Eten"]],
        "G1:J": [["Date"], [], [], [45369, 1234.56, SECRET_NAME, "Salaris"]]}}
    monkeypatch.setattr(ev, "load_exports", lambda paths: (txs, 0))
    monkeypatch.setattr(ev, "service_account_client", lambda p: FakeGc(books))
    monkeypatch.setattr(ev, "MIN_INTERVAL", 0.0)
    code = ev.main(["--dry-run", "--map", "Eten=Boodschappen", "x.csv"])
    out = capsys.readouterr().out
    assert code == 0
    assert "03/2024: expenses from row 4 (2 rows), income from row 4 (1 rows)" in out
    assert "scored: 2;" in out and "sheet rows no export row matched: 1" in out
    assert "dry run: nothing sent to the AI" in out
    for secret in (SECRET_NAME, SECRET_REM, "47.35", "1234.56", "9.99",
                   "17-03", "2024-03"):
        assert secret not in out


def test_a_failure_inside_main_withholds_its_message(monkeypatch, capsys,
                                                     root_logger):
    def broken(paths):
        raise RuntimeError(f"bad row {SECRET_NAME}")
    monkeypatch.setattr(ev, "load_exports", broken)
    assert ev.main(["--dry-run", "x.csv"]) == 2
    out = capsys.readouterr()
    assert "RuntimeError" in out.out and SECRET_NAME not in out.out + out.err


class RateLimited(Exception):
    """Shaped like gspread's APIError: the status sits on .response."""

    def __init__(self, status=429):
        super().__init__(f"quota exceeded for {SECRET_NAME}")
        self.response = SimpleNamespace(status_code=status)


class FlakyBook(FakeBook):
    def __init__(self, blocks, failures):
        super().__init__(blocks)
        self.failures = failures

    def values_batch_get(self, ranges, params=None):
        if self.failures:
            self.failures -= 1
            raise RateLimited()
        return super().values_batch_get(ranges, params)


BLOCKS = {"B1:E": [[45368, 1, "d", "Boodschappen"]], "G1:J": []}


def read(gc, picked, clock=lambda: 0.0):
    slept, lines = [], []
    rows = ev.read_sheets(gc, picked, "Transactions", lines.append,
                          sleep=slept.append, clock=clock)
    return rows, slept, lines


def test_sheet_reads_retry_a_rate_limit_with_long_waits():
    gc = FakeGc({"x": FlakyBook(BLOCKS, 2)})
    rows, slept, _ = read(gc, [("03/2024", "x")])
    assert len(rows) == 1
    assert [s for s in slept if s >= 20] == [20, 40]


def test_one_sheet_costs_two_requests():
    gc = FakeGc({"x": dict(BLOCKS)})
    read(gc, [("03/2024", "x")])
    assert gc.opened["x"].batch_calls == 1


def test_requests_are_spaced_out():
    """With a clock that never moves, every call after the first waits."""
    gc = FakeGc({"x": dict(BLOCKS), "y": dict(BLOCKS)})
    _, slept, _ = read(gc, [("03/2024", "x"), ("04/2024", "y")])
    assert slept == [ev.MIN_INTERVAL] * 3        # open, batch, open, batch


def test_no_wait_once_the_interval_has_passed():
    ticks = iter(range(0, 1000, 10))
    gc = FakeGc({"x": dict(BLOCKS), "y": dict(BLOCKS)})
    _, slept, _ = read(gc, [("03/2024", "x"), ("04/2024", "y")],
                       clock=lambda: float(next(ticks)))
    assert slept == []


def test_missing_tab_is_reported_and_skipped():
    gc = FakeGc({"x": FakeBook(BLOCKS, tab="Blad1")})
    rows, _, lines = read(gc, [("03/2024", "x")])
    assert rows == [] and "no 'Transactions' tab (tabs: ['Blad1'])" in lines[0]


def test_a_rate_limit_that_persists_still_stops_the_run():
    gc = FakeGc({"x": FlakyBook(BLOCKS, 10)})
    with pytest.raises(RateLimited):
        read(gc, [("03/2024", "x")])


def test_a_google_error_prints_its_status_but_not_its_message(capsys):
    def boom():
        raise RateLimited(403)
    assert ev.guarded(boom) == 2
    out = capsys.readouterr().out
    assert "RateLimited (HTTP 403)" in out and SECRET_NAME not in out
