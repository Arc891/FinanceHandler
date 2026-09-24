"""
Tests for finance_core.sheet_index, the authoritative month -> spreadsheet index.

The bot has no Drive listing scope, so this file cannot be rebuilt by
searching Drive (plan 4.2, 4.4). These tests pin the properties that make it
safe to own: labels are validated, ordering is chronological rather than
lexicographic, a label is never silently repointed, and writes are atomic.
"""

import json

import pytest

from finance_core.sheet_index import (
    IndexConflict,
    extract_spreadsheet_id,
    label_sort_key,
    load_index,
    parse_label,
    register,
    save_index,
)

ID_A = "1hLCziEA-8MgupWHC5gLDLpmd3ZJlrWZcbMwnCfk6f4M"
ID_B = "1lOmS_Cd3vqoZyi-4SBrT3GTrRP9akqcO8l_0uWUlXM8"


@pytest.mark.parametrize("label,expected", [
    ("01/2026", (2026, 1)),
    ("12/2025", (2025, 12)),
])
def test_parse_label_accepts_mm_yyyy(label, expected):
    assert parse_label(label) == expected


@pytest.mark.parametrize("label", ["1/2026", "13/2026", "00/2026", "2026/04", "04-2026", "", "04/26"])
def test_parse_label_rejects_everything_else(label):
    with pytest.raises(ValueError):
        parse_label(label)


def test_sort_key_is_chronological_across_a_year_boundary():
    labels = ["12/2026", "01/2027", "11/2026"]
    assert max(labels) == "12/2026"  # the trap: string order
    assert max(labels, key=label_sort_key) == "01/2027"
    assert sorted(labels, key=label_sort_key) == ["11/2026", "12/2026", "01/2027"]


@pytest.mark.parametrize("value", [
    ID_A,
    f"https://docs.google.com/spreadsheets/d/{ID_A}/edit",
    f"https://docs.google.com/spreadsheets/d/{ID_A}/edit?gid=0#gid=0",
    f"  https://docs.google.com/spreadsheets/d/{ID_A}  ",
])
def test_extract_id_from_url_or_bare_id(value):
    assert extract_spreadsheet_id(value) == ID_A


@pytest.mark.parametrize("value", ["", "not an id", "https://docs.google.com/document/d/abc/edit", "abc123"])
def test_extract_id_rejects_non_spreadsheet_input(value):
    with pytest.raises(ValueError):
        extract_spreadsheet_id(value)


def test_register_adds_a_new_label():
    index = {}
    assert register(index, "04/2026", ID_A) == "added"
    assert index["04/2026"] == {"id": ID_A, "created_by_bot": False, "created_at": None}


def test_register_same_id_twice_is_unchanged():
    index = {}
    register(index, "04/2026", ID_A)
    assert register(index, "04/2026", ID_A) == "unchanged"


def test_register_refuses_to_repoint_a_label():
    index = {}
    register(index, "04/2026", ID_A)
    with pytest.raises(IndexConflict, match="04/2026"):
        register(index, "04/2026", ID_B)
    assert index["04/2026"]["id"] == ID_A


def test_register_repoints_with_force():
    index = {}
    register(index, "04/2026", ID_A)
    assert register(index, "04/2026", ID_B, force=True) == "replaced"
    assert index["04/2026"]["id"] == ID_B


def test_register_refuses_one_sheet_under_two_labels():
    index = {}
    register(index, "04/2026", ID_A)
    with pytest.raises(IndexConflict, match="04/2026"):
        register(index, "05/2026", ID_A)
    assert "05/2026" not in index


def test_register_validates_the_label():
    with pytest.raises(ValueError):
        register({}, "4/2026", ID_A)


def test_load_missing_index_is_empty(tmp_path):
    assert load_index(tmp_path / "nope.json") == {}


def test_load_malformed_index_raises_naming_the_file(tmp_path):
    path = tmp_path / "sheet_index.json"
    path.write_text("{not json")
    with pytest.raises(ValueError, match="sheet_index.json"):
        load_index(path)


def test_load_rejects_an_entry_without_an_id(tmp_path):
    path = tmp_path / "sheet_index.json"
    path.write_text(json.dumps({"04/2026": {"created_by_bot": False}}))
    with pytest.raises(ValueError, match="04/2026"):
        load_index(path)


def test_save_round_trips_in_chronological_order(tmp_path):
    path = tmp_path / "sub" / "sheet_index.json"
    index = {}
    register(index, "01/2027", ID_A)
    register(index, "12/2026", ID_B)
    save_index(path, index)
    assert load_index(path) == index
    assert list(json.loads(path.read_text())) == ["12/2026", "01/2027"]


def test_save_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "sheet_index.json"
    save_index(path, {})
    assert [p.name for p in tmp_path.iterdir()] == ["sheet_index.json"]
