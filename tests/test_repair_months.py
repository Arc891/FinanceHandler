"""The month repair inspects structure only and writes only approved cells."""

import repair_months as repair
from constants import ExpenseCategory, IncomeCategory
from finance_core.sheet_registry import validation_requests


def index():
    return {f"{month:02d}/2026": {"id": f"private-id-{month}"}
            for month in range(1, 11)}


class FakeClient:
    def __init__(self):
        self.values = {}
        self.formats = {}
        self.calls = []
        self.labels = {
            "B27:B45": [c.value for c in ExpenseCategory if c.value != "Abonnementen"],
            "H27:H44": [c.value for c in IncomeCategory],
        }
        for target in repair.targets(index()):
            if target.name == "template" or target.name in repair.CREATED_MONTHS:
                self.values[target.name, "B36"] = "abonnementen"
            if target.name in repair.INCOME_MONTHS:
                self.values[target.name, "J35"] = ""
                self.formats[target.name, "Summary", "J34"] = {"numberFormat": {"type": "NUMBER"}}
                self.formats[target.name, "Summary", "K34"] = {"numberFormat": {"type": "CURRENCY"}}
                self.formats[target.name, "Summary", "J35"] = {}
                self.formats[target.name, "Summary", "K35"] = {}
            if target.name in repair.CREATED_MONTHS:
                for col in ("C", "H"):
                    self.formats[target.name, "Transactions", f"{col}5"] = {}
                    self.formats[target.name, "Transactions", f"{col}6"] = {
                        "numberFormat": {"type": "CURRENCY", "pattern": "€#,##0.00"}}

    def value(self, target, cell):
        return self.values.get((target.name, cell), "")

    def category_labels(self, target, a1):
        return self.labels[a1]

    def format(self, target, tab, cell):
        return self.formats.get((target.name, tab, cell), {})

    def validation_count(self, target):
        return 2

    def set_value(self, target, cell, value):
        self.calls.append((target.name, "set_value", cell, value))

    def copy_format(self, target, tab, source, destination, *, number_only=False):
        self.calls.append((target.name, "copy_format", tab, source, destination, number_only))

    def rebind_validations(self, target):
        self.calls.append((target.name, "rebind_validations"))


def test_targets_are_exact_and_missing_index_refuses():
    ts = repair.targets(index())
    assert [t.name for t in ts] == ["template"] + [f"{n:02d}/2026" for n in range(1, 11)]
    bad = index()
    del bad["08/2026"]
    try:
        repair.targets(bad)
    except ValueError as exc:
        assert "08/2026" in str(exc)
    else:
        assert False, "a missing month must not be silently skipped"


def test_default_dry_run_reports_cells_and_counts_without_writes_or_ids():
    client = FakeClient()
    lines = []
    assert repair.run([], client, index(), lines.append) == 0
    report = "\n".join(lines)
    assert "DRY RUN" in report
    assert "Transactions!C5" in report and "Transactions!H5" in report
    assert "Summary!B36" in report and "Summary!J35" in report
    assert "J35:K35" in report and "validation" in report
    assert "Abonnementen" in report
    assert "private-id" not in report
    assert client.calls == []


def test_apply_writes_only_requested_cells_and_formats():
    client = FakeClient()
    assert repair.run(["--apply"], client, index(), lambda *_: None) == 0
    assert [c for c in client.calls if c[1] == "set_value" and c[2] == "B36"] == [
        (name, "set_value", "B36", "Abonnementen")
        for name in ["template", *repair.CREATED_MONTHS]]
    assert [c for c in client.calls if c[1] == "set_value" and c[2] == "J35"] == [
        (name, "set_value", "J35", 0) for name in repair.INCOME_MONTHS]
    assert len([c for c in client.calls if c[1] == "rebind_validations"]) == 4
    assert len([c for c in client.calls if c[1] == "copy_format" and c[-1]]) == 8
    assert len([c for c in client.calls if c[1] == "copy_format" and not c[-1]]) == 8


def test_apply_is_all_or_nothing_when_a_cell_is_unexpected_and_does_not_print_value():
    client = FakeClient()
    client.values["03/2026", "J35"] = "private value"
    lines = []
    assert repair.run(["--apply"], client, index(), lines.append) == 1
    assert client.calls == []
    assert "private value" not in "\n".join(lines)


def test_existing_repaired_cells_are_skipped():
    client = FakeClient()
    client.values["template", "B36"] = "Abonnementen"
    client.labels["B27:B45"].append("Abonnementen")
    client.values["01/2026", "J35"] = 0
    client.formats["07/2026", "Transactions", "C5"] = client.formats[
        "07/2026", "Transactions", "C6"]
    assert repair.run(["--apply"], client, index(), lambda *_: None) == 0
    assert not any(c[:3] == ("template", "set_value", "B36") for c in client.calls)
    assert not any(c[:3] == ("01/2026", "set_value", "J35") for c in client.calls)
    assert not any(c[:5] == ("07/2026", "copy_format", "Transactions", "C6", "C5")
                   for c in client.calls)


def test_wrong_source_currency_format_refuses_all_writes():
    client = FakeClient()
    client.formats["09/2026", "Transactions", "C6"] = {"numberFormat": {"type": "NUMBER"}}
    assert repair.run(["--apply"], client, index(), lambda *_: None) == 1
    assert client.calls == []


def test_unexpected_template_category_mismatch_refuses_apply():
    client = FakeClient()
    client.labels["H27:H44"].remove("Salaris")
    lines = []
    assert repair.run(["--apply"], client, index(), lines.append) == 1
    assert client.calls == []
    assert "Salaris" in "\n".join(lines)


def test_validation_plan_groups_equal_rules_without_touching_values():
    rule = {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Summary!B27:B"}]}}
    got = {"sheets": [{"properties": {"sheetId": 7}, "data": [{
        "startRow": 4, "startColumn": 4,
        "rowData": [{"values": [{"dataValidation": rule}]},
                    {"values": [{"dataValidation": rule}]}]}]}]}
    requests = validation_requests(got, 7)
    assert len(requests) == 1
    assert requests[0]["setDataValidation"]["range"] == {
        "sheetId": 7, "startRowIndex": 4, "endRowIndex": 6,
        "startColumnIndex": 4, "endColumnIndex": 5}


def test_missing_months_are_discovered_by_exact_title_without_saving_index():
    partial = {k: v for k, v in index().items() if k not in repair.CREATED_MONTHS}
    calls = []

    def lookup(title):
        calls.append(title)
        return [f"found-{title[-7:]}"]

    merged = repair.discover_missing(partial, lookup)
    assert len(merged) == 10
    assert len(partial) == 6  # only the in-memory copy is extended
    assert calls == [f"Maandelijks Budget {name}" for name in repair.CREATED_MONTHS]


def test_discovery_refuses_missing_or_ambiguous_title():
    partial = {k: v for k, v in index().items() if k not in repair.CREATED_MONTHS}
    for found in ([], ["id-one", "id-two"]):
        try:
            repair.discover_missing(partial, lambda title: found)
        except ValueError as exc:
            assert "07/2026" in str(exc)
        else:
            assert False, "ambiguous or missing sheets must never be chosen"


def test_request_pacer_spaces_google_calls_without_delaying_the_first():
    now = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    class Request:
        def execute(self):
            return now[0]

    pacer = repair.RequestPacer(interval=1.5, clock=lambda: now[0], sleep=sleep)
    assert pacer.call(Request()) == 100.0
    assert pacer.call(Request()) == 101.5
    now[0] += 0.5
    assert pacer.call(Request()) == 103.0
    assert sleeps == [1.5, 1.0]
