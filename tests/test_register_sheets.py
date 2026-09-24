"""
Tests for scripts/register_sheets.py, which seeds and edits data/sheet_index.json.
"""

import io
import json

import register_sheets
from register_sheets import SEED_SHEETS, main

from finance_core.sheet_index import load_index


def run(argv, stdin=""):
    out = io.StringIO()
    code = main(argv, stdin=io.StringIO(stdin), stdout=out)
    return code, out.getvalue()


def test_seed_covers_the_2026_months_recorded_in_the_plan():
    assert list(SEED_SHEETS) == [f"{m:02d}/2026" for m in range(1, 7)]
    assert len(set(SEED_SHEETS.values())) == 6


def test_seed_writes_every_month(tmp_path):
    path = tmp_path / "sheet_index.json"
    code, _ = run(["seed", "--index", str(path)])
    assert code == 0
    index = load_index(path)
    assert {k: v["id"] for k, v in index.items()} == SEED_SHEETS
    assert all(v["created_by_bot"] is False for v in index.values())


def test_seed_is_idempotent(tmp_path):
    path = tmp_path / "sheet_index.json"
    run(["seed", "--index", str(path)])
    before = path.read_text()
    code, out = run(["seed", "--index", str(path)])
    assert code == 0
    assert path.read_text() == before
    assert "0 added" in out


def test_seed_keeps_months_registered_later(tmp_path):
    path = tmp_path / "sheet_index.json"
    run(["add", "07/2026", "1" + "x" * 43, "--index", str(path)])
    run(["seed", "--index", str(path)])
    assert "07/2026" in load_index(path)


def test_seed_conflict_writes_nothing(tmp_path):
    path = tmp_path / "sheet_index.json"
    path.write_text(json.dumps({"04/2026": {"id": "1" + "y" * 43, "created_by_bot": False, "created_at": None}}))
    before = path.read_text()
    code, out = run(["seed", "--index", str(path)])
    assert code == 1
    assert "04/2026" in out
    assert path.read_text() == before


def test_add_accepts_a_url(tmp_path):
    path = tmp_path / "sheet_index.json"
    sheet_id = "1" + "z" * 43
    code, _ = run(["add", "07/2026", f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit", "--index", str(path)])
    assert code == 0
    assert load_index(path)["07/2026"]["id"] == sheet_id


def test_add_bad_label_fails_without_writing(tmp_path):
    path = tmp_path / "sheet_index.json"
    code, out = run(["add", "7/2026", "1" + "z" * 43, "--index", str(path)])
    assert code == 1
    assert not path.exists()


def test_paste_reads_label_url_pairs_from_stdin(tmp_path):
    path = tmp_path / "sheet_index.json"
    a, b = "1" + "a" * 43, "1" + "b" * 43
    pasted = f"07/2026 https://docs.google.com/spreadsheets/d/{a}/edit\n\n# comment\n08/2026\t{b}\n"
    code, _ = run(["paste", "--index", str(path)], stdin=pasted)
    assert code == 0
    assert {k: v["id"] for k, v in load_index(path).items()} == {"07/2026": a, "08/2026": b}


def test_paste_with_one_bad_line_writes_nothing(tmp_path):
    path = tmp_path / "sheet_index.json"
    pasted = f"07/2026 {'1' + 'a' * 43}\n08/2026\n"
    code, out = run(["paste", "--index", str(path)], stdin=pasted)
    assert code == 1
    assert "line 2" in out
    assert not path.exists()


def test_list_prints_chronologically(tmp_path):
    path = tmp_path / "sheet_index.json"
    run(["add", "01/2027", "1" + "a" * 43, "--index", str(path)])
    run(["add", "12/2026", "1" + "b" * 43, "--index", str(path)])
    code, out = run(["list", "--index", str(path)])
    assert code == 0
    assert out.index("12/2026") < out.index("01/2027")


def test_default_index_path_is_under_data():
    assert register_sheets.DEFAULT_INDEX_PATH.endswith("data/sheet_index.json")
