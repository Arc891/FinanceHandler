"""
Tests for finance_core.periods, the pure period splitter (plan 4.3).

Every rule of 4.3 has at least one test here, and the scenarios of plan
section 5 are covered one by one. Two of them are adjusted where the plan's
own numbers contradict its constants; each such test says so in its
docstring. All rows are synthetic.
"""

from datetime import date

import pytest

from finance_core.periods import (
    Anchor,
    SuspiciousSplitError,
    _check_split,
    advance_anchor,
    anchor_from_state,
    anchor_to_state,
    label_for_boundary,
    split_into_periods,
)

MARKERS = [r"\bDUO\b", r"Anamata"]


def d(text):
    day, month, year = (int(p) for p in text.split("-"))
    return date(year, month, day)


def tx(when, amount=-12.5, name="Picnic", remittance="Boodschappen"):
    """A transaction dict in csv_helper's shape. Positive amounts are income."""
    income = amount > 0
    return {
        "booking_date": when,
        "transaction_amount": {"amount": f"{amount:.2f}", "currency": "EUR"},
        "credit_debit_indicator": "CRDT" if income else "DBIT",
        "debtor": {"name": "" if income else name},
        "creditor": {"name": name if income else ""},
        "remittance_information": [remittance] if remittance else [],
    }


def duo(when, amount=450.0):
    return tx(when, amount, "DUO Hoofdrekening", "Studiefinanciering")


def salary(when, amount=2400.0):
    return tx(when, amount, "Anamata B.V.", "5-3215930-01-07-NL00TEST-Anamata B.V.-SALARISBETALING PERIODE 4")


def split(txs, anchor=None, force=False, **overrides):
    kwargs = dict(anchor=anchor, markers=MARKERS, min_amount=250.0, min_days=20,
                  max_days=35, step_days=29, split_day=15, force=force)
    kwargs.update(overrides)
    return split_into_periods(txs, **kwargs)


def labels_by_date(result):
    """{booking_date: {labels}} over every row of the result."""
    out = {}
    for period in result.periods:
        for t in period.transactions:
            out.setdefault(t["booking_date"], set()).add(t["period_label"])
    return out


def label_of(result, when):
    found = labels_by_date(result)[when]
    assert len(found) == 1, f"{when} landed in {found}"
    return next(iter(found))


# The real 2026 boundaries (plan section 11): the anchor of the backlog walk
# and the history seed_state.py reads off the sheets, newest first.
BACKLOG_ANCHOR = Anchor(
    boundary=d("24-04-2026"), label="05/2026",
    history=((d("23-03-2026"), "04/2026"), (d("24-02-2026"), "03/2026"),
             (d("23-01-2026"), "02/2026"), (d("24-12-2025"), "01/2026")),
)


# ── Rule 6: labels ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("boundary,label", [
    ("14-03-2026", "03/2026"),
    ("15-03-2026", "04/2026"),
    ("01-03-2026", "03/2026"),
    ("24-03-2026", "04/2026"),
    ("24-12-2026", "01/2027"),
    ("14-12-2026", "12/2026"),
])
def test_label_for_boundary_uses_the_split_day(boundary, label):
    assert label_for_boundary(d(boundary), 15) == label


def test_boundary_on_day_14_and_day_15_through_the_splitter():
    early = split([duo("14-03-2026"), tx("20-03-2026")])
    late = split([duo("15-03-2026"), tx("20-03-2026")])
    assert [p.label for p in early.periods] == ["03/2026"]
    assert [p.label for p in late.periods] == ["04/2026"]


# ── Rule 1: candidates ──────────────────────────────────────────────────────

def test_duo_then_salary_the_next_day_is_one_boundary():
    result = split([tx("22-03-2026"), duo("24-03-2026"), salary("25-03-2026"), tx("26-03-2026")])
    assert result.boundaries == [(d("24-03-2026"), "04/2026")]
    assert [p.label for p in result.periods] == ["03/2026", "04/2026"]
    opened = result.periods[1]
    assert opened.kind == "open" and opened.start == d("24-03-2026")
    assert opened.boundary_row["creditor"]["name"] == "DUO Hoofdrekening"


def test_duo_repayment_is_not_a_candidate():
    repayment = tx("24-03-2026", -450.0, "DUO Hoofdrekening", "Aflossing")
    result = split([repayment, tx("26-03-2026")], anchor=Anchor(d("24-02-2026"), "03/2026"))
    assert result.boundaries == []
    assert {p.label for p in result.periods} == {"03/2026"}


def test_salary_from_a_private_person_is_not_a_candidate():
    private = tx("24-03-2026", 900.0, "Persoon A", "Salaris Janneke")
    result = split([private, tx("26-03-2026")], anchor=Anchor(d("24-02-2026"), "03/2026"))
    assert result.boundaries == []


def test_marker_income_below_the_amount_floor_is_not_a_candidate():
    small = tx("24-03-2026", 249.99, "DUO Hoofdrekening", "Terugbetaling")
    result = split([small, tx("26-03-2026")], anchor=Anchor(d("24-02-2026"), "03/2026"))
    assert result.boundaries == []
    assert split([duo("24-03-2026", 250.0)]).boundaries == [(d("24-03-2026"), "04/2026")]


def test_marker_in_the_remittance_alone_is_enough():
    wired = tx("24-03-2026", 2400.0, "Persoon B", "Doorboeking Anamata salaris")
    assert split([wired]).boundaries == [(d("24-03-2026"), "04/2026")]


# ── Rule 2: clustering ──────────────────────────────────────────────────────

def test_clusters_are_measured_from_the_cluster_boundary_not_chained():
    """
    Plan section 5 phrases this as candidates 24, 25 and 43 days after a
    boundary, but 43 - 24 = 19 is inside min_days = 20, so under the plan's own
    constants that third candidate joins the second cluster whichever way it is
    measured. The property the test exists for -- no chaining -- needs
    candidates that split the two readings: 0, 15, 30. Chained, 30 is 15 days
    after 15 and would join; measured from the cluster boundary it is 30 days
    out and opens a new one.
    """
    rows = [duo("01-03-2026"), salary("16-03-2026"), duo("31-03-2026"), tx("02-04-2026")]
    result = split(rows)
    assert [b for b, _ in result.boundaries] == [d("01-03-2026"), d("31-03-2026")]


def test_a_candidate_19_days_after_the_cluster_boundary_joins_it():
    result = split([duo("01-03-2026"), salary("20-03-2026"), tx("22-03-2026")])
    assert [b for b, _ in result.boundaries] == [d("01-03-2026")]
    assert {p.label for p in result.periods} == {"03/2026"}


# ── Rule 3: anchor continuity ───────────────────────────────────────────────

def test_the_anchors_own_boundary_seen_again_opens_no_period():
    anchor = Anchor(d("24-03-2026"), "04/2026")
    result = split([duo("24-03-2026"), salary("25-03-2026"), tx("30-03-2026")], anchor=anchor)
    assert result.boundaries == []
    assert [p.label for p in result.periods] == ["04/2026"]


def test_a_candidate_inside_the_anchor_window_does_not_swallow_the_real_boundary():
    """A spurious candidate 15 days after the anchor is discarded before clustering."""
    anchor = Anchor(d("24-03-2026"), "04/2026")
    rows = [salary("08-04-2026"), tx("10-04-2026"), duo("23-04-2026"), tx("25-04-2026")]
    result = split(rows, anchor=anchor)
    assert result.boundaries == [(d("23-04-2026"), "05/2026")]
    assert label_of(result, "10-04-2026") == "04/2026"
    assert label_of(result, "25-04-2026") == "05/2026"


# ── Rule 4: leading rows ────────────────────────────────────────────────────

def test_leading_rows_inside_the_anchor_window_get_the_anchor_label():
    anchor = Anchor(d("24-03-2026"), "04/2026")
    result = split([tx("16-04-2026"), tx("20-04-2026")], anchor=anchor)
    assert [(p.label, p.kind) for p in result.periods] == [("04/2026", "leading")]
    assert result.warnings == []


def test_marker_less_export_without_anchor_uses_the_split_rule_with_a_warning():
    result = split([tx("16-04-2026"), tx("20-04-2026")])
    assert [p.label for p in result.periods] == ["05/2026"]
    assert result.warnings


def test_leading_rows_without_anchor_get_the_previous_label_with_a_warning():
    result = split([tx("10-03-2026"), duo("24-03-2026"), tx("26-03-2026")])
    assert [(p.label, p.kind) for p in result.periods] == [("03/2026", "leading"), ("04/2026", "open")]
    assert result.warnings


def test_one_step_before_the_oldest_boundary_is_the_previous_label():
    anchor = Anchor(d("24-04-2026"), "05/2026")          # no history
    result = split([tx("26-03-2026"), tx("23-04-2026"), tx("24-04-2026")], anchor=anchor)
    assert label_of(result, "26-03-2026") == "04/2026"   # 29 days back: one step
    assert label_of(result, "23-04-2026") == "04/2026"
    assert label_of(result, "24-04-2026") == "05/2026"


def test_two_steps_before_the_oldest_boundary_aborts():
    anchor = Anchor(d("24-04-2026"), "05/2026")
    with pytest.raises(SuspiciousSplitError) as err:
        split([tx("25-03-2026"), tx("24-04-2026")], anchor=anchor)   # 30 days back
    assert "25-03-2026" in str(err.value)


def test_two_steps_back_with_force_are_labelled_by_the_step_rule():
    anchor = Anchor(d("24-04-2026"), "05/2026")
    result = split([tx("24-02-2026"), tx("25-03-2026"), tx("24-04-2026")], anchor=anchor, force=True)
    assert label_of(result, "25-03-2026") == "03/2026"   # 30 days: two steps
    assert label_of(result, "24-02-2026") == "02/2026"   # 59 days: three steps


def test_a_row_31_days_before_the_anchor_uses_the_real_interval_in_history():
    """Revision 4's fixed 30-day step made this two steps and aborted the run."""
    anchor = Anchor(d("24-04-2026"), "05/2026", history=((d("24-03-2026"), "04/2026"),))
    result = split([tx("24-03-2026"), tx("25-04-2026")], anchor=anchor)
    assert label_of(result, "24-03-2026") == "04/2026"


def test_rows_older_than_the_whole_history_fall_back_to_the_step_rule():
    anchor = Anchor(d("24-04-2026"), "05/2026", history=((d("23-03-2026"), "04/2026"),))
    ok = split([tx("22-02-2026"), tx("25-04-2026")], anchor=anchor)       # 29 days before 23-03
    assert label_of(ok, "22-02-2026") == "03/2026"
    with pytest.raises(SuspiciousSplitError):
        split([tx("21-02-2026"), tx("25-04-2026")], anchor=anchor)       # 30 days: two steps


def test_sixty_day_overlap_across_the_real_04_2026_period_labels_every_row():
    """The DUO rows of 23-03 and 24-04 are in the overlap and must open nothing."""
    rows = [tx("22-03-2026"), duo("23-03-2026"), tx("15-04-2026"), tx("23-04-2026"),
            duo("24-04-2026"), tx("21-05-2026")]
    result = split(rows, anchor=BACKLOG_ANCHOR)
    assert result.boundaries == []
    assert label_of(result, "22-03-2026") == "03/2026"
    assert label_of(result, "23-03-2026") == "04/2026"
    assert label_of(result, "23-04-2026") == "04/2026"
    assert label_of(result, "24-04-2026") == "05/2026"
    assert label_of(result, "21-05-2026") == "05/2026"
    assert [p.label for p in result.periods] == ["03/2026", "04/2026", "05/2026"]
    assert all(p.kind == "leading" for p in result.periods)


def test_december_january_rollover_backwards():
    anchor = Anchor(d("24-12-2025"), "01/2026")
    result = split([tx("30-11-2025"), tx("30-12-2025")], anchor=anchor)
    assert label_of(result, "30-11-2025") == "12/2025"
    assert label_of(result, "30-12-2025") == "01/2026"


def test_december_january_rollover_forwards():
    anchor = Anchor(d("24-11-2026"), "12/2026")
    result = split([tx("20-12-2026"), duo("24-12-2026"), tx("02-01-2027")], anchor=anchor)
    assert [p.label for p in result.periods] == ["12/2026", "01/2027"]


# ── Rule 5: rows beyond the anchor window ───────────────────────────────────

def test_marker_less_export_beyond_the_window_aborts_even_with_force():
    anchor = Anchor(d("24-03-2026"), "04/2026")
    for force in (False, True):
        with pytest.raises(SuspiciousSplitError) as err:
            split([tx("20-04-2026"), tx("28-04-2026")], anchor=anchor, force=force)
        assert "re-export from 24-03-2026" in str(err.value)


def test_the_window_edge_is_max_days():
    """
    Plan section 5 asks that a row 32 days after the anchor is *not* given the
    anchor label, but with max_days = 35 a marker-less row 32 days out is
    inside the window by 4.3's own rule. The property it guards -- revision 4's
    40-day window swallowed rows that belong to the next month -- is the edge
    itself: day 34 is the anchor's, day 35 is not.
    """
    anchor = Anchor(d("24-03-2026"), "04/2026")
    inside = split([tx("27-04-2026")], anchor=anchor)             # 34 days
    assert label_of(inside, "27-04-2026") == "04/2026"
    with pytest.raises(SuspiciousSplitError):
        split([tx("28-04-2026")], anchor=anchor)                  # 35 days


def test_a_row_32_days_out_after_a_boundary_in_the_file_is_the_next_month():
    anchor = Anchor(d("24-03-2026"), "04/2026")
    result = split([tx("20-04-2026"), duo("23-04-2026"), tx("25-04-2026")], anchor=anchor)
    assert label_of(result, "25-04-2026") == "05/2026"


def test_rows_past_the_window_before_a_late_boundary_stay_with_the_anchor():
    """A boundary 36 days after the anchor still closes the anchor's period."""
    anchor = Anchor(d("01-03-2026"), "03/2026")
    result = split([tx("05-04-2026"), duo("06-04-2026"), tx("07-04-2026")], anchor=anchor)
    assert label_of(result, "05-04-2026") == "03/2026"
    assert label_of(result, "07-04-2026") == "04/2026"


def test_marker_less_export_without_anchor_spanning_max_days_aborts():
    with pytest.raises(SuspiciousSplitError):
        split([tx("16-04-2026"), tx("21-05-2026")], force=True)


# ── Rule 7: contiguity and length ───────────────────────────────────────────

def test_december_bonus_after_a_12_2026_period_aborts_listing_both_boundaries():
    rows = [salary("20-11-2026"), tx("25-11-2026"), salary("10-12-2026", 800.0), tx("12-12-2026")]
    with pytest.raises(SuspiciousSplitError) as err:
        split(rows)
    assert err.value.boundaries == [(d("20-11-2026"), "12/2026"), (d("10-12-2026"), "12/2026")]
    assert "20-11-2026" in str(err.value) and "10-12-2026" in str(err.value)


def test_december_bonus_with_force_keeps_the_labels_and_creates_no_january():
    rows = [salary("20-11-2026"), tx("25-11-2026"), salary("10-12-2026", 800.0), tx("12-12-2026")]
    result = split(rows, force=True)
    assert {p.label for p in result.periods} == {"12/2026"}
    assert result.warnings


def test_january_plus_march_with_february_missing_aborts():
    rows = [tx("10-01-2026"), duo("23-01-2026"), tx("28-01-2026"),
            tx("10-03-2026"), duo("23-03-2026"), tx("28-03-2026")]
    with pytest.raises(SuspiciousSplitError) as err:
        split(rows)
    assert [label for _, label in err.value.boundaries] == ["02/2026", "04/2026"]


def test_january_plus_march_with_force_names_the_skipped_month():
    rows = [tx("10-01-2026"), duo("23-01-2026"), tx("28-01-2026"),
            tx("10-03-2026"), duo("23-03-2026"), tx("28-03-2026")]
    result = split(rows, force=True)
    assert label_of(result, "28-03-2026") == "04/2026"
    assert result.skipped_labels == ["03/2026"]
    assert any("03/2026" in w for w in result.warnings)


def test_first_boundary_must_follow_the_anchor_label():
    anchor = Anchor(d("24-03-2026"), "04/2026")
    rows = [tx("30-03-2026"), duo("24-05-2026"), tx("26-05-2026")]      # 04/2026 -> 06/2026
    with pytest.raises(SuspiciousSplitError):
        split(rows, anchor=anchor)
    forced = split(rows, anchor=anchor, force=True)
    assert forced.skipped_labels == ["05/2026"]
    assert label_of(forced, "30-03-2026") == "04/2026"


def test_short_leading_and_open_periods_are_exempt():
    rows = [tx("19-03-2026"), duo("24-03-2026"), tx("20-04-2026"),
            duo("23-04-2026"), tx("25-04-2026")]
    result = split(rows)                                   # 5-day leading, 3-day open
    assert [(p.label, p.kind) for p in result.periods] == [
        ("03/2026", "leading"), ("04/2026", "closed"), ("05/2026", "open")]


def test_a_closed_period_shorter_than_min_days_aborts():
    """
    Clustering (rule 2) and anchor continuity (rule 3) already keep accepted
    boundaries min_days apart, so a short closed period cannot come out of
    split_into_periods today. Rule 7 keeps the length check as its own guard
    against a future change to clustering, so it is tested directly.
    """
    problems, skipped = _check_split(
        [(d("24-03-2026"), "04/2026"), (d("05-04-2026"), "05/2026"), (d("05-05-2026"), "06/2026")],
        anchor=None, min_days=20)
    assert skipped == []
    assert len(problems) == 1 and "12 days" in problems[0]
    anchored, _ = _check_split([(d("05-04-2026"), "05/2026")],
                               anchor=Anchor(d("24-03-2026"), "04/2026"), min_days=20)
    assert "12 days" in anchored[0]


# ── Rules 8 and 9 ───────────────────────────────────────────────────────────

def test_rows_on_the_boundary_date_listed_before_the_duo_row_join_the_new_period():
    rows = [tx("23-03-2026"), tx("24-03-2026", name="Albert Heijn"), duo("24-03-2026")]
    result = split(rows)
    assert labels_by_date(result)["24-03-2026"] == {"04/2026"}
    assert label_of(result, "23-03-2026") == "03/2026"


def test_count_in_equals_count_out_and_every_row_is_labelled():
    rows = [tx("22-05-2026"), duo("24-05-2026"), tx("24-05-2026"), tx("24-05-2026"),
            tx("10-06-2026"), salary("23-06-2026"), tx("01-07-2026")]
    result = split(rows, anchor=BACKLOG_ANCHOR)
    out = [t for p in result.periods for t in p.transactions]
    assert len(out) == len(rows)
    assert all("period_label" in t for t in out)


def test_the_input_rows_are_not_modified():
    rows = [tx("22-05-2026"), duo("24-05-2026")]
    split(rows, anchor=BACKLOG_ANCHOR)
    assert all("period_label" not in t for t in rows)


def test_periods_come_out_in_date_order_whatever_the_input_order():
    rows = [tx("01-07-2026"), salary("23-06-2026"), tx("22-05-2026"), duo("24-05-2026")]
    result = split(rows, anchor=BACKLOG_ANCHOR)
    assert [p.label for p in result.periods] == ["05/2026", "06/2026", "07/2026"]
    for p in result.periods:
        dates = [d(t["booking_date"]) for t in p.transactions]
        assert dates == sorted(dates)


def test_an_unparsable_date_raises():
    with pytest.raises(ValueError):
        split([tx("2026-05-24")])


def test_an_empty_upload_is_an_empty_split():
    result = split([], anchor=BACKLOG_ANCHOR)
    assert result.periods == [] and result.boundaries == []


# ── The real 2026 history ───────────────────────────────────────────────────

def test_the_real_2026_spans_replayed_as_the_backlog_walk():
    """Anchor 24-04 -> 05/2026, export 22-05 to 21-09 (plan 4.3 and section 11)."""
    rows = [tx("22-05-2026"), tx("23-05-2026"),
            duo("24-05-2026"), salary("25-05-2026"), tx("20-06-2026"),
            duo("23-06-2026"), salary("25-06-2026"), tx("20-07-2026"),
            duo("24-07-2026"), salary("24-07-2026"), tx("20-08-2026"),
            duo("24-08-2026"), salary("25-08-2026"), tx("21-09-2026")]
    result = split(rows, anchor=BACKLOG_ANCHOR)
    assert [(p.label, p.kind) for p in result.periods] == [
        ("05/2026", "leading"), ("06/2026", "closed"), ("07/2026", "closed"),
        ("08/2026", "closed"), ("09/2026", "open")]
    assert result.periods[0].start == d("22-05-2026")
    assert [b for b, _ in result.boundaries] == [
        d("24-05-2026"), d("23-06-2026"), d("24-07-2026"), d("24-08-2026")]
    assert result.warnings == [] and result.skipped_labels == []


# ── Anchor lifecycle ────────────────────────────────────────────────────────

def test_advance_moves_to_the_last_boundary_and_keeps_every_superseded_one():
    rows = [tx("22-05-2026"), duo("24-05-2026"), duo("23-06-2026"), tx("30-06-2026")]
    result = split(rows, anchor=BACKLOG_ANCHOR)
    new = advance_anchor(BACKLOG_ANCHOR, result)
    assert (new.boundary, new.label) == (d("23-06-2026"), "07/2026")
    assert new.history[:2] == ((d("24-05-2026"), "06/2026"), (d("24-04-2026"), "05/2026"))
    assert new.history[2:] == BACKLOG_ANCHOR.history


def test_advance_without_new_boundaries_keeps_the_anchor():
    result = split([tx("10-05-2026")], anchor=BACKLOG_ANCHOR)
    assert advance_anchor(BACKLOG_ANCHOR, result) == BACKLOG_ANCHOR
    assert advance_anchor(None, split([tx("10-05-2026")])) is None


def test_advance_from_no_anchor():
    result = split([tx("10-03-2026"), duo("24-03-2026"), duo("23-04-2026")])
    new = advance_anchor(None, result)
    assert (new.boundary, new.label) == (d("23-04-2026"), "05/2026")
    assert new.history == ((d("24-03-2026"), "04/2026"),)


def test_the_advanced_anchor_labels_a_later_overlapping_export():
    first = split([tx("22-05-2026"), duo("24-05-2026"), tx("20-06-2026")], anchor=BACKLOG_ANCHOR)
    anchor = advance_anchor(BACKLOG_ANCHOR, first)
    again = split([tx("20-05-2026"), duo("24-05-2026"), tx("21-06-2026")], anchor=anchor)
    assert again.boundaries == []
    assert label_of(again, "20-05-2026") == "05/2026"
    assert label_of(again, "21-06-2026") == "06/2026"


def test_anchor_state_round_trip():
    state = anchor_to_state(BACKLOG_ANCHOR)
    assert state["anchor"] == {"boundary": "24-04-2026", "label": "05/2026"}
    assert state["history"][0] == ["23-03-2026", "04/2026"]
    assert anchor_from_state(state) == BACKLOG_ANCHOR
    assert anchor_to_state(None) is None and anchor_from_state(None) is None


def test_anchor_rejects_a_history_out_of_order():
    with pytest.raises(ValueError):
        Anchor(d("24-04-2026"), "05/2026", history=((d("24-02-2026"), "03/2026"),
                                                    (d("23-03-2026"), "04/2026")))
    with pytest.raises(ValueError):
        Anchor(d("24-04-2026"), "05/2026", history=((d("24-04-2026"), "05/2026"),))
    with pytest.raises(ValueError):
        Anchor(d("24-04-2026"), "5/2026")
