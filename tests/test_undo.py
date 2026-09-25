"""
Tests for scripts/undo_upload.py (plan 4.6): content-addressed undo from the
write audit, anchor restore, and --drop-created.
"""

import json
from datetime import date

from finance_core.ledger import Ledger
from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.sheet_index import load_index, save_index
from finance_core.sheet_writer import commit_append, read_block, sort_by_date

import undo_upload

from fakes import FakeWorkbooks, expense_tx, income_tx, make_month, serial

NOT_APPENDING = lambda sid: False  # noqa: E731


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.wb = FakeWorkbooks()
        self.ledger_path = tmp_path / "upload_ledger.json"
        self.index_path = tmp_path / "sheet_index.json"
        self.state_path = tmp_path / "period_state.json"
        self.runs_dir = tmp_path / "runs"
        self.runs_dir.mkdir()
        self.ledger = Ledger(self.ledger_path)
        self.index = {}

    def month(self, label, sheet_id, rows=0, created_by=None):
        sh = self.wb.add_book(make_month(sheet_id, label))
        if rows:
            sh.transactions.resize(rows=rows + 60)
            sh.transactions.put("B5", [[serial(date(2026, 5, 1 + i % 28)), 3.0 + i, f"pre {i}", "Boodschappen"]
                                       for i in range(rows)])
        entry = {"id": sheet_id, "created_by_bot": created_by is not None, "created_at": None}
        if created_by:
            entry["upload_id"] = created_by
        self.index[label] = entry
        save_index(self.index_path, self.index)
        return sh

    def write(self, upload_id, label, sh, block, txs):
        """The COMMIT sequence of plan 4.6 for one block."""
        self.ledger.record_written(upload_id, label, txs)
        pairs = commit_append(sh, block, txs, failed_path=self.tmp / "failed.json")
        self.ledger.record_audit(upload_id, sh.id, block.name, pairs)

    def run(self, *argv):
        out = []
        code = undo_upload.main(
            list(argv) + ["--ledger", str(self.ledger_path), "--index", str(self.index_path),
                          "--period-state", str(self.state_path), "--runs-dir", str(self.runs_dir)],
            workbooks=self.wb, stdout_write=out.append)
        return code, "".join(out)


def snapshot(sh, block=EXPENSES):
    contents = read_block(sh, block)
    return contents.tuples, contents.cells


def expenses(n, seq0=0):
    return [expense_tx(date_str=f"{1 + i % 28:02d}-05-2026", amount=f"-{7 + i}.25", seq=str(seq0 + i),
                       description=f"new {i}") for i in range(n)]


def test_append_sort_undo_restores_the_block(tmp_path):
    env = Env(tmp_path)
    sh = env.month("05/2026", "sheet-05", rows=100)
    before = snapshot(sh)
    env.ledger.start_run("u1", None)
    env.write("u1", "05/2026", sh, EXPENSES, expenses(20))
    sort_by_date(sh, is_appending=NOT_APPENDING)
    assert snapshot(sh) != before
    code, out = env.run("u1")
    assert code == 0
    after = snapshot(sh)
    assert sorted(after[0]) == sorted(before[0])            # content restored
    assert len(after[0]) == 100
    assert "removed 20" in out and "not found 0" in out


def test_undo_restores_the_anchor_including_history(tmp_path):
    env = Env(tmp_path)
    anchor = {"anchor": {"boundary": "24-04-2026", "label": "05/2026"},
              "history": [["24-03-2026", "04/2026"], ["24-04-2026", "05/2026"]]}
    env.state_path.write_text(json.dumps({"anchor": {"boundary": "24-08-2026", "label": "09/2026"}}))
    env.ledger.start_run("u1", anchor)
    assert env.run("u1")[0] == 0
    assert json.loads(env.state_path.read_text()) == anchor


def test_undo_removes_the_period_state_when_there_was_none_before(tmp_path):
    env = Env(tmp_path)
    env.state_path.write_text("{}")
    env.ledger.start_run("u1", None)
    assert env.run("u1")[0] == 0
    assert not env.state_path.exists()


def test_crash_between_record_written_and_commit_undoes_to_a_no_op(tmp_path):
    env = Env(tmp_path)
    sh = env.month("05/2026", "sheet-05", rows=10)
    before = snapshot(sh)
    env.ledger.start_run("u1", None)
    env.ledger.record_written("u1", "05/2026", expenses(3))     # ... and then the process died
    code, _ = env.run("u1")
    assert code == 0
    assert snapshot(sh) == before
    assert sh.transactions.updates() == []


def test_a_pre_existing_row_equal_to_a_recorded_one_survives(tmp_path):
    env = Env(tmp_path)
    sh = env.month("05/2026", "sheet-05")
    tx = expense_tx(date_str="03-05-2026", amount="-2.50", description="Koffie", category="Uit eten", seq="1")
    sh.transactions.put("B5", [[serial(date(2026, 5, 3)), 2.5, "Koffie", "Uit eten"]])   # the user's own row
    env.ledger.start_run("u1", None)
    env.write("u1", "05/2026", sh, EXPENSES, [tx])
    env.run("u1")
    assert len(read_block(sh, EXPENSES).tuples) == 1


def test_not_found_is_reported_not_raised(tmp_path):
    env = Env(tmp_path)
    sh = env.month("05/2026", "sheet-05")
    env.ledger.start_run("u1", None)
    env.write("u1", "05/2026", sh, EXPENSES, expenses(2))
    sh.transactions.batch_clear(["B5:E5"])                       # the user deleted one by hand
    code, out = env.run("u1")
    assert code == 0
    assert "removed 1" in out and "not found 1" in out


def test_income_and_expense_blocks_are_both_undone(tmp_path):
    env = Env(tmp_path)
    sh = env.month("06/2026", "sheet-06")
    env.ledger.start_run("u1", None)
    env.write("u1", "06/2026", sh, EXPENSES, expenses(2))
    env.write("u1", "06/2026", sh, INCOME, [income_tx(seq="i1")])
    env.run("u1")
    assert read_block(sh, EXPENSES).tuples == [] and read_block(sh, INCOME).tuples == []


def test_drop_created_trashes_only_this_runs_created_sheets(tmp_path):
    env = Env(tmp_path)
    env.month("06/2026", "sheet-06")
    env.month("07/2026", "sheet-07", created_by="u0")          # created by an earlier run
    made = env.month("08/2026", "sheet-08", created_by="u1")
    env.ledger.start_run("u1", None)
    env.write("u1", "08/2026", made, EXPENSES, expenses(2))
    code, _ = env.run("u1", "--drop-created")
    assert code == 0
    assert list(load_index(env.index_path)) == ["06/2026", "07/2026"]
    assert env.wb.trashed == {"sheet-08"}
    assert env.wb.ops("trash_file") == [("trash_file", "sheet-08")]


def test_without_drop_created_the_created_sheet_stays(tmp_path):
    env = Env(tmp_path)
    made = env.month("08/2026", "sheet-08", created_by="u1")
    env.ledger.start_run("u1", None)
    env.write("u1", "08/2026", made, EXPENSES, expenses(2))
    env.run("u1")
    assert "08/2026" in load_index(env.index_path)
    assert env.wb.trashed == set()
    assert read_block(made, EXPENSES).tuples == []


def test_undo_refuses_while_a_period_is_appending_and_says_resume_first(tmp_path):
    env = Env(tmp_path)
    sh = env.month("05/2026", "sheet-05", rows=5)
    env.ledger.start_run("u1", None)
    env.write("u1", "05/2026", sh, EXPENSES, expenses(2))
    (env.runs_dir / "u2.json").write_text(json.dumps(
        {"periods": [{"label": "05/2026", "sheet_id": "sheet-05", "status": "appending"}]}))
    before = snapshot(sh)
    code, out = env.run("u1")
    assert code != 0
    assert snapshot(sh) == before
    assert out.index("/resume") < out.index("undo")


def test_after_undo_the_rows_are_new_again(tmp_path):
    env = Env(tmp_path)
    sh = env.month("05/2026", "sheet-05")
    txs = expenses(3)
    env.ledger.start_run("u1", None)
    env.write("u1", "05/2026", sh, EXPENSES, txs)
    env.run("u1")
    new, skipped = Ledger(env.ledger_path).filter_new(txs)
    assert len(new) == 3 and skipped == []


def test_unknown_upload_id_fails_cleanly(tmp_path):
    env = Env(tmp_path)
    code, out = env.run("nope")
    assert code != 0 and "nope" in out


def test_second_undo_is_refused(tmp_path):
    env = Env(tmp_path)
    env.ledger.start_run("u1", None)
    assert env.run("u1")[0] == 0
    code, out = env.run("u1")
    assert code != 0 and "already undone" in out


def test_dry_run_changes_nothing(tmp_path):
    env = Env(tmp_path)
    sh = env.month("05/2026", "sheet-05")
    env.ledger.start_run("u1", {"anchor": None})
    env.write("u1", "05/2026", sh, EXPENSES, expenses(2))
    before = snapshot(sh)
    code, out = env.run("u1", "--dry-run")
    assert code == 0 and "would remove 2" in out
    assert snapshot(sh) == before
    assert not env.state_path.exists()
    assert Ledger(env.ledger_path).run("u1")["undone_at"] is None
