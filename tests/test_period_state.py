"""
Tests for finance_core.period_state, the file behind the period anchor.

The ledger stores the file's full JSON as a run's anchor_before and
undo_upload.py writes it back verbatim (plan 4.3, 4.6), so the raw read and
write must round-trip exactly, and a missing file must mean "no anchor".
"""

import json
from datetime import date

import pytest

from finance_core.period_state import load_anchor, read_state, save_anchor, split_settings, write_state
from finance_core.periods import Anchor

ANCHOR = Anchor(date(2026, 4, 24), "05/2026", history=((date(2026, 3, 23), "04/2026"),))


def test_missing_file_is_no_anchor(tmp_path):
    path = tmp_path / "period_state.json"
    assert read_state(path) is None
    assert load_anchor(path) is None


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "data" / "period_state.json"
    save_anchor(path, ANCHOR)
    assert load_anchor(path) == ANCHOR
    assert json.loads(path.read_text()) == {
        "anchor": {"boundary": "24-04-2026", "label": "05/2026"},
        "history": [["23-03-2026", "04/2026"]],
    }


def test_raw_state_is_what_undo_writes_back(tmp_path):
    path = tmp_path / "period_state.json"
    save_anchor(path, ANCHOR)
    before = read_state(path)
    save_anchor(path, Anchor(date(2026, 5, 24), "06/2026", history=((ANCHOR.boundary, ANCHOR.label),)))
    write_state(path, before)
    assert load_anchor(path) == ANCHOR


def test_writing_none_removes_the_file(tmp_path):
    path = tmp_path / "period_state.json"
    save_anchor(path, ANCHOR)
    write_state(path, None)
    assert not path.exists()
    write_state(path, None)                    # already absent: no error


def test_a_malformed_file_raises(tmp_path):
    path = tmp_path / "period_state.json"
    path.write_text("{not json")
    with pytest.raises(ValueError):
        load_anchor(path)
    path.write_text(json.dumps({"anchor": {"boundary": "2026-04-24", "label": "05/2026"}}))
    with pytest.raises(ValueError):
        load_anchor(path)


def test_split_settings_default_to_the_plan_constants():
    settings = split_settings()
    assert settings == {
        "markers": [r"\bDUO\b", r"Anamata"],
        "min_amount": 250.0,
        "min_days": 20,
        "max_days": 35,
        "step_days": 29,
        "split_day": 15,
    }
