"""
The period splitter against tests/fixtures/multi_month.csv (plan 4.3, Phase 2).

The fixture is the user's anonymised 12-06-2026 to 25-09-2026 export: 390
rows, boundary markers on 24-06, 24-07, 24-08 and 24-09-2026, so a leading
remainder into 06/2026 and then 07/2026 to 10/2026. These tests assert
structure only -- labels, dates, counts -- and print no row content.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest

from finance_core.csv_helper import load_transactions_from_csv
from finance_core.periods import Anchor, advance_anchor, parse_date, split_into_periods

FIXTURE = Path(__file__).parent / "fixtures" / "multi_month.csv"
SETTINGS = dict(markers=[r"\bDUO\b", r"Anamata"], min_amount=250.0, min_days=20,
                max_days=35, step_days=29, split_day=15)
BOUNDARIES = [(date(2026, 6, 24), "07/2026"), (date(2026, 7, 24), "08/2026"),
              (date(2026, 8, 24), "09/2026"), (date(2026, 9, 24), "10/2026")]
# The anchor the backlog would leave behind at 24-05 (plan 4.3's walk, one month on).
ANCHOR = Anchor(date(2026, 5, 24), "06/2026", history=(
    (date(2026, 4, 24), "05/2026"), (date(2026, 3, 23), "04/2026"),
    (date(2026, 2, 24), "03/2026"), (date(2026, 1, 23), "02/2026"),
    (date(2025, 12, 24), "01/2026")))


@pytest.fixture(scope="module")
def txs(tmp_path_factory):
    # csv_helper writes a normalised copy beside its input; keep it out of tests/.
    path = tmp_path_factory.mktemp("fixture") / FIXTURE.name
    shutil.copy(FIXTURE, path)
    return load_transactions_from_csv(str(path))


def test_fixture_loads_whole(txs):
    assert len(txs) == 390


@pytest.mark.parametrize("anchor", [None, ANCHOR], ids=["no-anchor", "anchored"])
def test_fixture_splits_into_the_expected_periods(txs, anchor):
    result = split_into_periods(txs, anchor=anchor, **SETTINGS)
    assert result.boundaries == BOUNDARIES
    assert [(p.label, p.kind) for p in result.periods] == [
        ("06/2026", "leading"), ("07/2026", "closed"), ("08/2026", "closed"),
        ("09/2026", "closed"), ("10/2026", "open")]
    assert result.periods[0].start == date(2026, 6, 12)
    assert result.skipped_labels == []
    # Only the anchorless split warns: its leading label is a guess.
    assert bool(result.warnings) is (anchor is None)


def test_every_fixture_row_lands_in_its_period_and_none_is_lost(txs):
    result = split_into_periods(txs, anchor=ANCHOR, **SETTINGS)
    out = [t for p in result.periods for t in p.transactions]
    assert len(out) == len(txs) == 390
    edges = [p.start for p in result.periods[1:]] + [date.max]
    for period, end in zip(result.periods, edges):
        assert period.transactions, period.label
        for t in period.transactions:
            assert t["period_label"] == period.label
            assert period.start <= parse_date(t["booking_date"]) < end


def test_each_fixture_boundary_is_opened_by_a_marker_income_row(txs):
    result = split_into_periods(txs, anchor=ANCHOR, **SETTINGS)
    for period in result.periods[1:]:
        row = period.boundary_row
        assert row["credit_debit_indicator"] == "CRDT"
        assert parse_date(row["booking_date"]) == period.start


def test_reuploading_the_fixture_under_the_advanced_anchor_labels_every_row_the_same(txs):
    """
    What an overlapping re-export sees when the ledger did not net a row out:
    the advanced anchor and its history must reproduce the first run's labels
    without opening a single new period.
    """
    first = split_into_periods(txs, anchor=ANCHOR, **SETTINGS)
    anchor = advance_anchor(ANCHOR, first)
    assert (anchor.boundary, anchor.label) == (date(2026, 9, 24), "10/2026")
    again = split_into_periods(txs, anchor=anchor, **SETTINGS)
    assert again.boundaries == [] and again.warnings == []

    def labels(result):
        return sorted((t["bank_sequence_no"], t["period_label"])
                      for p in result.periods for t in p.transactions)
    assert labels(again) == labels(first)
