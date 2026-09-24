"""
Tests for scripts/add_income_placeholder.py.

The script writes one text label into Summary!H35, which switches on the
guarded SUMIF already sitting in K35 (plan 4.9, section 11). It must write
that one cell and nothing else, refuse any sheet that does not look exactly
like the template, and do nothing at all unless --apply is given.
"""

import pytest

import add_income_placeholder as aip
from constants import ExpenseCategory
from register_sheets import SEED_SHEETS

K35 = '=if(isblank($H35); ""; sumif(Transactions!$J:$J;$H35;Transactions!$H:$H))'


class FakeSummary:
    def __init__(self, h35="", k35=K35):
        self.values = {"H35": h35}
        self.formulas = {"K35": k35}
        self.writes = []

    def read_value(self, cell):
        return self.values.get(cell, "")

    def read_formula(self, cell):
        return self.formulas.get(cell, "")

    def write_text(self, cell, value):
        self.writes.append((cell, value))
        self.values[cell] = value


def test_label_is_the_existing_placeholder_category():
    assert aip.LABEL == ExpenseCategory.NOG_IN_TEDELEN.value


def test_targets_are_the_template_and_every_seeded_month():
    names = [name for name, _ in aip.targets()]
    assert names[0] == "template"
    assert names[1:] == list(SEED_SHEETS)
    ids = [sheet_id for _, sheet_id in aip.targets()]
    assert ids[0] == aip.TEMPLATE_ID
    assert len(set(ids)) == len(ids)


def test_clean_sheet_dry_run_writes_nothing():
    tab = FakeSummary()
    result = aip.patch_summary(tab, apply=False)
    assert result.action == "would-write"
    assert tab.writes == []


def test_clean_sheet_apply_writes_exactly_h35():
    tab = FakeSummary()
    result = aip.patch_summary(tab, apply=True)
    assert result.action == "written"
    assert tab.writes == [("H35", aip.LABEL)]


def test_non_empty_h35_is_refused():
    tab = FakeSummary(h35="Iets anders")
    result = aip.patch_summary(tab, apply=True)
    assert result.action == "refused"
    assert "H35" in result.detail
    assert tab.writes == []


def test_already_labelled_sheet_is_left_alone():
    tab = FakeSummary(h35=aip.LABEL)
    result = aip.patch_summary(tab, apply=True)
    assert result.action == "already-done"
    assert tab.writes == []


@pytest.mark.parametrize("k35", [
    "",
    "=sum(K27:K34)",
    '=sumif(Transactions!$J:$J;$H35;Transactions!$H:$H)',  # unguarded
    '=if(isblank($H34); ""; sumif(Transactions!$J:$J;$H34;Transactions!$H:$H))',  # wrong row
])
def test_unexpected_k35_is_refused(k35):
    tab = FakeSummary(k35=k35)
    result = aip.patch_summary(tab, apply=True)
    assert result.action == "refused"
    assert "K35" in result.detail
    assert tab.writes == []


@pytest.mark.parametrize("k35", [
    K35,
    '=IF(ISBLANK($H35), "", SUMIF(Transactions!$J:$J,$H35,Transactions!$H:$H))',
    '=if(isblank($H35);"";sumif(Transactions!$J:$J;$H35;Transactions!$H:$H))',
])
def test_k35_matches_regardless_of_case_separator_and_spacing(k35):
    assert aip.patch_summary(FakeSummary(k35=k35), apply=False).action == "would-write"


def test_write_that_does_not_read_back_is_reported():
    class Lossy(FakeSummary):
        def write_text(self, cell, value):
            self.writes.append((cell, value))  # value never lands

    result = aip.patch_summary(Lossy(), apply=True)
    assert result.action == "failed"


def test_run_defaults_to_dry_run():
    tabs = {name: FakeSummary() for name, _ in aip.targets()}
    code = aip.run([], open_summary=lambda name, sheet_id: tabs[name], out=lambda *_: None)
    assert code == 0
    assert all(t.writes == [] for t in tabs.values())


def test_run_apply_patches_every_clean_sheet_and_reports_refusals():
    tabs = {name: FakeSummary() for name, _ in aip.targets()}
    tabs["03/2026"] = FakeSummary(h35="Iets anders")
    lines = []
    code = aip.run(["--apply"], open_summary=lambda name, sheet_id: tabs[name], out=lines.append)
    assert code == 1  # a refusal is a non-zero exit
    assert tabs["03/2026"].writes == []
    assert all(t.writes == [("H35", aip.LABEL)] for n, t in tabs.items() if n != "03/2026")
    assert any("03/2026" in line and "refused" in line for line in lines)


def test_run_only_limits_the_targets():
    tabs = {name: FakeSummary() for name, _ in aip.targets()}
    aip.run(["--apply", "--only", "template"], open_summary=lambda name, sheet_id: tabs[name], out=lambda *_: None)
    assert tabs["template"].writes == [("H35", aip.LABEL)]
    assert all(t.writes == [] for n, t in tabs.items() if n != "template")


def test_run_prints_the_rollback_line():
    lines = []
    aip.run([], open_summary=lambda name, sheet_id: FakeSummary(), out=lines.append)
    assert any("rollback" in line.lower() for line in lines)
