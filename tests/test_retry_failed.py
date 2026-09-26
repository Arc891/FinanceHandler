"""
Tests for scripts/retry_failed_transactions.py on the new layer (plan 4.10,
Phase 4 step 1).

A failed write leaves an entry in failed_uploads.json holding the rows,
their upload_id, period_label and block. The script re-appends those rows
into the indexed sheet for the label, but never rows /resume still owes (an
open run holds them) and never a row the sheet already has (the failed write
may have landed after all). What it writes goes into the ledger audit, so
undo_upload.py can reverse it. It prints counts only. All data is synthetic.
"""

import json

import pytest

import retry_failed_transactions as retry
from fakes import expense_tx, income_tx
from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.run_state import RunStore
from finance_core.sheet_writer import intended_cells
from finance_core.row_tuple import canonical
from pipeline_env import Env

SECRET = "Jolanda Vermeulen"
LABEL = "06/2026"


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path, months=(LABEL,))


def entry(upload_id="u-closed", label=LABEL, block="expenses", txs=None,
          sheet_id="id-06-2026"):
    return {"upload_id": upload_id, "period_label": label,
            "spreadsheet_id": sheet_id, "block": block,
            "error": "APIError: 500", "failed_at": "2026-09-26T10:00:00+00:00",
            "transactions": txs if txs is not None else
            [expense_tx("25-06-2026", "-12.50", seq="1",
                        description=f"Etentje {SECRET}", category="Uit eten"),
             expense_tx("26-06-2026", "-7.25", seq="2")]}


def write_failed(env, *entries):
    env.failed_path.write_text(json.dumps({"failed": list(entries)}))


def failed(env):
    return json.loads(env.failed_path.read_text())["failed"]


def open_run(env, upload_id):
    RunStore(str(env.runs_dir)).create(upload_id, files=[], force=False,
                                       upload_dir=None, anchor_before=None)


def closed_run(env, upload_id):
    store = RunStore(str(env.runs_dir))
    run = store.create(upload_id, files=[], force=False, upload_dir=None,
                       anchor_before=None)
    store.close(run, "complete")


def run_script(env, *extra, registry=None):
    out = []
    code = retry.main(
        ["--failed", str(env.failed_path), "--runs-dir", str(env.runs_dir),
         "--ledger", str(env.ledger_path), *extra],
        registry=registry or env.registry(), stdout_write=out.append)
    return code, "".join(out)


def cells(tx):
    return canonical(intended_cells(tx))


# ── what gets written ───────────────────────────────────────────────────────

def test_rows_of_a_closed_run_are_appended_and_the_entry_removed(env):
    closed_run(env, "u-closed")
    e = entry()
    write_failed(env, e)
    code, out = run_script(env)
    assert code == 0
    rows = env.block_rows(LABEL, EXPENSES)
    assert len(rows) == 2
    assert failed(env) == []
    assert "appended 2" in out


def test_an_entry_with_no_run_at_all_is_retried(env):
    write_failed(env, entry(upload_id="u-unknown"))
    run_script(env)
    assert len(env.block_rows(LABEL, EXPENSES)) == 2


def test_income_goes_to_the_income_block(env):
    write_failed(env, entry(block="income", txs=[income_tx("24-06-2026")]))
    run_script(env)
    assert len(env.block_rows(LABEL, INCOME)) == 1
    assert env.block_rows(LABEL, EXPENSES) == []


def test_written_rows_are_audited_so_undo_can_remove_them(env):
    e = entry(upload_id="u-closed")
    write_failed(env, e)
    run_script(env)
    audit = env.ledger().audited_rows("u-closed")
    assert sorted(audit["id-06-2026"]["expenses"]) == \
        sorted(cells(tx) for tx in e["transactions"])


# ── what is never written ───────────────────────────────────────────────────

def test_an_open_runs_entry_is_skipped_and_kept(env):
    """/resume owes those rows; writing them here too writes them twice."""
    open_run(env, "u-open")
    write_failed(env, entry(upload_id="u-open"))
    code, out = run_script(env)
    assert env.block_rows(LABEL, EXPENSES) == []
    assert len(failed(env)) == 1
    assert "open run" in out and "/resume" in out


def test_rows_already_in_the_sheet_are_not_appended_again(env):
    """The failed write may have landed after all (a timeout after success)."""
    e = entry()
    write_failed(env, e)
    sh = env.sheet(LABEL)
    from finance_core.sheet_writer import commit_append
    commit_append(sh, EXPENSES, e["transactions"][:1],
                  failed_path=str(env.tmp / "scratch.json"))
    code, out = run_script(env)
    assert len(env.block_rows(LABEL, EXPENSES)) == 2
    assert failed(env) == []
    assert "already in the sheet 1" in out


def test_already_present_is_a_multiset(env):
    """Two identical rows owed, one already there: one is appended."""
    same = [expense_tx("25-06-2026", "-3.00", seq="1", description="Koffie"),
            expense_tx("25-06-2026", "-3.00", seq="2", description="Koffie")]
    write_failed(env, entry(txs=same))
    from finance_core.sheet_writer import commit_append
    commit_append(env.sheet(LABEL), EXPENSES, same[:1],
                  failed_path=str(env.tmp / "scratch.json"))
    run_script(env)
    assert len(env.block_rows(LABEL, EXPENSES)) == 2


def test_a_label_missing_from_the_index_keeps_its_entry(env):
    write_failed(env, entry(label="09/2026"))
    code, out = run_script(env)
    assert len(failed(env)) == 1
    assert "09/2026" in out and "index" in out
    assert code == 1


def test_an_old_format_entry_is_reported_and_left_alone(env):
    legacy = {"user_id": 1, "transaction_type": "expense",
              "transaction": expense_tx(description=SECRET)}
    write_failed(env, legacy)
    code, out = run_script(env)
    assert failed(env) == [legacy]
    assert "old format" in out
    assert env.block_rows(LABEL, EXPENSES) == []


def test_a_failing_append_keeps_one_entry_and_counts_the_attempt(env, monkeypatch):
    write_failed(env, entry())
    ws = env.sheet(LABEL).transactions

    def boom(*args, **kwargs):
        raise RuntimeError(f"HTTP 500 while writing {SECRET}")
    monkeypatch.setattr(ws, "update", boom)
    code, out = run_script(env)
    assert SECRET not in out
    left = failed(env)
    assert len(left) == 1
    assert left[0]["attempts"] == 1
    assert left[0]["error"].startswith("RuntimeError")
    assert code == 1


def test_one_failing_entry_does_not_stop_the_others(env, monkeypatch):
    env2 = Env(env.tmp / "two", months=(LABEL, "07/2026"))
    write_failed(env2, entry(label="07/2026", sheet_id="id-07-2026"), entry())
    ws = env2.sheet("07/2026").transactions
    monkeypatch.setattr(ws, "update", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("HTTP 500")))
    run_script(env2)
    assert len(env2.block_rows(LABEL, EXPENSES)) == 2
    assert [e["period_label"] for e in failed(env2)] == ["07/2026"]


# ── dry run and privacy ─────────────────────────────────────────────────────

def test_dry_run_changes_nothing(env):
    write_failed(env, entry())
    before = env.failed_path.read_text()
    code, out = run_script(env, "--dry-run")
    assert code == 0
    assert env.block_rows(LABEL, EXPENSES) == []
    assert env.failed_path.read_text() == before
    assert "would append 2" in out


def test_output_holds_no_row_content(env):
    open_run(env, "u-open")
    write_failed(env, entry(), entry(upload_id="u-open"),
                 {"user_id": 1, "transaction": expense_tx(description=SECRET)})
    _, out = run_script(env)
    for secret in (SECRET, "Jolanda", "12.50", "Etentje"):
        assert secret not in out


def test_no_file_means_nothing_to_do(env):
    code, out = run_script(env)
    assert code == 0 and "nothing" in out.lower()
