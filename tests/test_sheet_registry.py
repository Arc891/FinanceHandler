"""
Tests for finance_core.sheet_registry (plan 4.4).

`resolve` may create, `lookup` never does. The index is authoritative; months
are created only from the template, only when adjacent to the newest indexed
month, and only after a fidelity check that proves flagged rows reach the totals.
"""

import threading
from functools import partial

import pytest

from finance_core.google_retry import with_retry
from finance_core.sheet_index import load_index, save_index
from finance_core.sheet_registry import (MissingSheetError, RegistryConfig, SheetLayoutError,
                                         SheetRegistry, StaleSheetError)
from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.sheet_writer import read_block

from fakes import FakeHttpError, FakeWorkbooks, make_month

no_sleep_retry = partial(with_retry, sleep=lambda s: None)


def seeded(tmp_path, labels, **month_kw):
    wb = FakeWorkbooks()
    index = {}
    for i, label in enumerate(labels):
        sid = f"id-{label.replace('/', '-')}"
        wb.add_book(make_month(sid, label, **month_kw.get(label, {})))
        index[label] = {"id": sid, "created_by_bot": False, "created_at": None}
    path = tmp_path / "sheet_index.json"
    save_index(path, index)
    return wb, path


def registry(wb, path, **overrides):
    cfg = RegistryConfig(index_path=str(path), template_id=FakeWorkbooks.TEMPLATE_ID,
                         folder_id=FakeWorkbooks.FOLDER_ID, **overrides)
    return SheetRegistry(wb, cfg, retry=no_sleep_retry)


# ── index hits ───────────────────────────────────────────────────────────────

def test_index_hit_opens_by_key_and_verifies(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    result = registry(wb, path).resolve("06/2026")
    assert result.spreadsheet.id == "id-06-2026"
    assert result.created is False
    assert wb.ops("create_workbook") == []


def test_index_hit_with_wrong_header_is_a_layout_error(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.books["id-06-2026"].transactions.put("D4", [["Omschrijving"]])
    with pytest.raises(SheetLayoutError, match="header"):
        registry(wb, path).resolve("06/2026")


def test_index_hit_with_wrong_title_is_a_layout_error(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.books["id-06-2026"].title = "Maandelijks Budget 05/2026"
    with pytest.raises(SheetLayoutError, match="title"):
        registry(wb, path).resolve("06/2026")


def test_stale_id_is_its_own_error_and_never_recreates(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.trashed.add("id-06-2026")
    with pytest.raises(StaleSheetError) as err:
        registry(wb, path).resolve("06/2026")
    assert "06/2026" in str(err.value) and "id-06-2026" in str(err.value)
    assert wb.ops("create_workbook") == []


def test_lookup_returns_none_for_a_miss_and_never_creates(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    assert registry(wb, path).lookup("07/2026") is None
    assert wb.ops("create_workbook") == []


# ── misses and adjacency ─────────────────────────────────────────────────────

def test_miss_with_auto_create_off_names_months_register(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    with pytest.raises(MissingSheetError, match="/months register"):
        registry(wb, path, auto_create=False).resolve("07/2026")


def test_non_adjacent_miss_raises_even_with_auto_create(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    with pytest.raises(MissingSheetError, match="09/2026"):
        registry(wb, path).resolve("09/2026")
    assert wb.ops("create_workbook") == []


def test_create_nonadjacent_permits_a_gap(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    result = registry(wb, path, create_nonadjacent=True).resolve("09/2026")
    assert result.created


def test_a_miss_before_the_newest_month_is_not_adjacent(tmp_path):
    wb, path = seeded(tmp_path, ["04/2026", "06/2026"])
    with pytest.raises(MissingSheetError):
        registry(wb, path).resolve("05/2026")


def test_adjacency_is_chronological_not_lexicographic(tmp_path):
    wb, path = seeded(tmp_path, ["11/2026", "12/2026", "01/2027"])
    result = registry(wb, path).resolve("02/2027")
    assert result.created
    assert "02/2027" in load_index(path)


def test_backlog_sequence_creates_each_next_month(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    reg = registry(wb, path)
    for label in ("07/2026", "08/2026", "09/2026"):
        assert reg.resolve(label).created
    assert list(load_index(path)) == ["06/2026", "07/2026", "08/2026", "09/2026"]


def test_empty_index_permits_any_label(tmp_path):
    wb = FakeWorkbooks()
    result = registry(wb, tmp_path / "sheet_index.json").resolve("03/2031")
    assert result.created


# ── create ───────────────────────────────────────────────────────────────────

def test_create_passes_the_templates_locale_time_zone_and_recalc(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    registry(wb, path).resolve("07/2026")
    (_, title, locale, tz, recalc), = wb.ops("create_workbook")
    assert title == "Maandelijks Budget 07/2026"
    assert (locale, tz, recalc) == ("nl_NL", "Europe/Monaco", "ON_CHANGE")


def test_copy_order_is_transactions_rename_summary_rename_rebind_delete_reorder(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    registry(wb, path).resolve("07/2026")
    steps = [(op, args[-1] if op == "rename_tab" else None)
             for op, *args in wb.ops("copy_tab", "rename_tab", "rebind_validations", "delete_tab", "move_tab")]
    assert steps == [("copy_tab", None), ("rename_tab", "Transactions"),
                     ("copy_tab", None), ("rename_tab", "Summary"),
                     ("rebind_validations", None),
                     ("delete_tab", None), ("move_tab", None)]
    copies = wb.ops("copy_tab")
    tabs = wb.books[FakeWorkbooks.TEMPLATE_ID]
    assert copies[0][2] == tabs.worksheet("Transactions").id
    assert copies[1][2] == tabs.worksheet("Summary").id


def test_created_months_dropdowns_are_bound_to_its_own_summary(tmp_path):
    # Transactions is copied before the new workbook has a Summary, so its
    # category rules arrive unbound: every value read "Ongeldig" (07/2026 live)
    wb, path = seeded(tmp_path, ["06/2026"])
    sh = registry(wb, path).resolve("07/2026").spreadsheet
    rules = sh.transactions.validations
    assert rules["E5"]["bound"] and rules["J5"]["bound"]
    (_, sheet_id, tab_id), = wb.ops("rebind_validations")
    assert (sheet_id, tab_id) == (sh.id, sh.transactions.id)


def test_fidelity_leaves_the_templates_row_formats_in_the_first_data_row(tmp_path):
    # The probe row used to be blanked with RAW "", which strips the number
    # format: the first amount of 07-10/2026 showed as a bare number
    wb, path = seeded(tmp_path, ["06/2026"])
    sh = registry(wb, path).resolve("07/2026").spreadsheet
    template = wb.books[FakeWorkbooks.TEMPLATE_ID].transactions
    for col in (2, 3, 7, 8):                                   # B, C, G, H
        assert sh.transactions.formats.get((5, col)) == template.formats[(5, col)]


def test_fidelity_fails_when_row_formats_differ_from_the_next_row(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    template = wb.books[FakeWorkbooks.TEMPLATE_ID].transactions
    template.formats.pop((5, 3))
    with pytest.raises(SheetLayoutError, match="C5"):
        registry(wb, path).resolve("07/2026")
    assert wb.created_ids() == []


def test_fidelity_fails_when_a_category_is_not_exactly_a_summary_label(tmp_path):
    # SUMIF ignores case, so 'abonnementen' still counts, but a label that
    # differs from what the bot writes is how rows drop out of the totals
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.summary_kw = {"relabel": {"Abonnementen": "abonnementen"}}
    with pytest.raises(SheetLayoutError, match="'Abonnementen'"):
        registry(wb, path).resolve("07/2026")
    assert wb.created_ids() == []
    assert "07/2026" not in load_index(path)


def test_created_workbook_has_summary_first_and_no_default_tab(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    sh = registry(wb, path).resolve("07/2026").spreadsheet
    assert [ws.title for ws in sh.worksheets()] == ["Summary", "Transactions"]


def test_created_month_is_moved_into_the_folder_and_indexed_as_bot_created(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    result = registry(wb, path).resolve("07/2026", upload_id="u-7")
    entry = load_index(path)["07/2026"]
    assert entry["id"] == result.spreadsheet.id
    assert entry["created_by_bot"] is True and entry["upload_id"] == "u-7" and entry["created_at"]
    assert wb.parent[result.spreadsheet.id] == [FakeWorkbooks.FOLDER_ID]
    assert result.left_in_root is False


def test_folder_403_leaves_the_month_in_root_but_the_run_succeeds(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.folder_writable = False
    result = registry(wb, path).resolve("07/2026")
    assert result.created and result.left_in_root
    assert load_index(path)["07/2026"]["id"] == result.spreadsheet.id
    assert "07/2026" in result.notes()[0]


def test_fidelity_leaves_the_new_month_empty(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    sh = registry(wb, path).resolve("07/2026").spreadsheet
    assert read_block(sh, EXPENSES).tuples == [] and read_block(sh, INCOME).tuples == []
    summary = sh.worksheet("Summary")
    assert summary.get("E26", value_render_option="UNFORMATTED_VALUE") == [[0]]


def test_fidelity_fails_when_a_flagged_income_row_does_not_reach_the_totals(tmp_path):
    # The income total stops short of the placeholder row: a label-presence check passes this.
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.summary_kw = {"income_bound": 34}
    with pytest.raises(SheetLayoutError, match="K26"):
        registry(wb, path).resolve("07/2026")
    assert wb.created_ids() == []                           # the orphan was deleted
    assert "07/2026" not in load_index(path)               # and nothing was indexed


def test_fidelity_fails_without_the_category_validation(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.copy_validations = False
    with pytest.raises(SheetLayoutError, match="E5"):
        registry(wb, path).resolve("07/2026")
    assert wb.created_ids() == []
    assert "07/2026" not in load_index(path)


def test_fidelity_fails_on_a_stray_extra_tab(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.extra_copy = True
    with pytest.raises(SheetLayoutError, match="tabs"):
        registry(wb, path).resolve("07/2026")
    assert wb.created_ids() == []


def test_fidelity_fails_on_a_locale_mismatch(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    original = wb.create_workbook

    def en_us(title, locale, time_zone, auto_recalc):
        return original(title, "en_US", time_zone, auto_recalc)

    wb.create_workbook = en_us
    with pytest.raises(SheetLayoutError, match="locale"):
        registry(wb, path).resolve("07/2026")
    assert wb.created_ids() == []


def test_a_copy_failure_deletes_the_orphan(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.faults["copy_tab"] = [FakeHttpError(400)]
    with pytest.raises(FakeHttpError):
        registry(wb, path).resolve("07/2026")
    assert wb.created_ids() == []
    assert "07/2026" not in load_index(path)


def test_transient_errors_on_copy_are_retried(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.faults["copy_tab"] = [FakeHttpError(503), FakeHttpError(429)]
    assert registry(wb, path).resolve("07/2026").created


# ── starting balance (step 7) ────────────────────────────────────────────────

def summary_l8(sh):
    return sh.worksheet("Summary").get("L8", value_render_option="UNFORMATTED_VALUE")


def test_l8_is_set_from_the_previous_months_e17(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"], **{"06/2026": {"rows": 3, "l8": 1000.0}})
    result = registry(wb, path).resolve("07/2026")
    assert summary_l8(result.spreadsheet) == [[970]]       # 1000 - 3 x 10
    assert result.needs_starting_balance is False


def test_l8_is_set_when_the_previous_month_was_written_in_this_run(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"], **{"06/2026": {"rows": 1, "l8": 50.0}})
    result = registry(wb, path).resolve("07/2026", period_status={"06/2026": "written"}.get)
    assert summary_l8(result.spreadsheet) == [[40]]


def test_no_l8_while_the_previous_month_is_appending(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"], **{"06/2026": {"rows": 2, "l8": 100.0}})
    result = registry(wb, path).resolve("07/2026", period_status={"06/2026": "appending"}.get)
    assert summary_l8(result.spreadsheet) == []
    assert result.needs_starting_balance
    assert any("starting balance" in n for n in result.notes())


def test_no_l8_from_an_empty_previous_month(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"], **{"06/2026": {"l8": 100.0}})
    result = registry(wb, path).resolve("07/2026")
    assert summary_l8(result.spreadsheet) == []
    assert result.needs_starting_balance


def test_starting_balance_uses_lookup_and_never_creates(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"], **{"06/2026": {"rows": 2, "l8": 100.0}})
    result = registry(wb, path, create_nonadjacent=True).resolve("09/2026")
    assert len(wb.ops("create_workbook")) == 1
    assert list(load_index(path)) == ["06/2026", "09/2026"]
    assert result.needs_starting_balance


# ── register, list, lock ─────────────────────────────────────────────────────

def test_register_and_list_months(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.add_book(make_month("hand-made", "07/2026"))
    reg = registry(wb, path)
    assert reg.register("07/2026", "https://docs.google.com/spreadsheets/d/hand-made/edit") == "added"
    assert [label for label, _ in reg.list_months()] == ["06/2026", "07/2026"]
    assert reg.resolve("07/2026").created is False


def test_register_verifies_the_sheet_before_indexing(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    wb.add_book(make_month("wrong-title-0123456789abcdefghij", "05/2026"))
    with pytest.raises(SheetLayoutError):
        registry(wb, path).register("07/2026", "wrong-title-0123456789abcdefghij")
    assert "07/2026" not in load_index(path)


def test_two_concurrent_resolves_create_the_label_once(tmp_path):
    wb, path = seeded(tmp_path, ["06/2026"])
    reg = registry(wb, path)
    wb.books[FakeWorkbooks.TEMPLATE_ID].transactions.get_delay = 0.01
    results = []
    threads = [threading.Thread(target=lambda: results.append(reg.resolve("07/2026"))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wb.ops("create_workbook")) == 1
    assert len({r.spreadsheet.id for r in results}) == 1
