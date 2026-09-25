"""
Tests for the append contract's RECONCILE path (plan 4.6, section 5 test_reconcile.py).

Every case crashes a run at one exact point of the COMMIT sequence, then lets a
freshly started pipeline /resume it. ``Crash`` is a BaseException, so nothing
in the pipeline catches it: the state files are left exactly as a killed
process would leave them.
"""

from collections import Counter
from datetime import date

import pytest

from fakes import FakeHttpError, serial
from pipeline_env import Crash, Env, row

from finance_core.ledger import Ledger, strong_key
from finance_core.row_tuple import EXPENSES, INCOME, canonical
from finance_core.sheet_writer import read_block, remove_rows, sort_by_date

NOT_APPENDING = lambda sid: False  # noqa: E731
PASS = ("pass", None)              # an update_faults entry that lets the write through


class CrashingLedger(Ledger):
    """Raises Crash on the ``nth`` call of ``op``, before or after the real call."""

    def __init__(self, path, op, *, nth=1, after=False):
        super().__init__(path)
        self.op, self.nth, self.after, self.seen = op, nth, after, 0

    def _maybe(self, op, fn, *args):
        if op == self.op:
            self.seen += 1
            if self.seen == self.nth and not self.after:
                raise Crash()
        out = fn(*args)
        if op == self.op and self.seen == self.nth and self.after:
            raise Crash()
        return out

    def record_written(self, *args):
        return self._maybe("record_written", super().record_written, *args)

    def record_audit(self, *args):
        return self._maybe("record_audit", super().record_audit, *args)


def pre_rows(env, rows, label="06/2026"):
    """Pre-existing expense rows: (day, amount, description) in June 2026."""
    env.sheet(label).transactions.put(
        "B5", [[serial(date(2026, 6, d)), amt, desc, "Boodschappen"] for d, amt, desc in rows])


def as_tuples(env, block=EXPENSES, label="06/2026"):
    return [canonical(r) for r in env.block_rows(label, block)]


def sheet_row(tx_row, description=None):
    """The RowTuple FakeEngine's ai_auto result makes of a synthetic row."""
    d, m, y = (int(x) for x in tx_row[0].split("-"))
    return (date(y, m, d).isoformat(), f"{abs(float(tx_row[10])):.2f}",
            description or f"Desc {tx_row[15]}", "Boodschappen")


async def crash_upload(env, rows, *, ledger=None):
    with pytest.raises(Crash):
        await env.upload(rows, pipeline=env.pipeline(ledger=ledger))
    return env.pipeline().store.open_runs()[-1]["upload_id"]


def income(day, amount="20.00"):
    return row(f"{day:02d}-06-2026", amount=amount, counterparty="Tikkie", remittance="terug")


# ── positional path ──────────────────────────────────────────────────────────

async def test_identical_preexisting_row_placed_last_does_not_hide_an_unlanded_row(tmp_path):
    env = Env(tmp_path)
    tx = row("10-06-2026", amount="-11.25", seq="X1")
    pre_rows(env, [(1, 3.0, "a"), (2, 4.0, "b"), (10, 11.25, "Desc X1")])     # last == intended
    env.sheet("06/2026").transactions.update_faults = [("before", Crash())]
    upload_id = await crash_upload(env, [tx])
    await env.pipeline().resume()
    assert Counter(as_tuples(env))[sheet_row(tx)] == 2
    assert env.period(upload_id, "06/2026")["reconcile"]["expenses"] == "positional"


async def test_two_identical_intended_rows_both_land(tmp_path):
    env = Env(tmp_path)
    twins = [row("10-06-2026", amount="-5.00", remittance="SAME"),
             row("10-06-2026", amount="-5.00", remittance="SAME")]
    assert strong_key_of(twins[0]) != strong_key_of(twins[1])
    env.sheet("06/2026").transactions.update_faults = [("before", Crash())]
    await crash_upload(env, twins)
    await env.pipeline().resume()
    assert Counter(as_tuples(env))[sheet_row(twins[0], "Same")] == 2


async def test_expense_landed_income_did_not_appends_only_income(tmp_path):
    env = Env(tmp_path)
    rows = [row("10-06-2026"), row("11-06-2026"), income(12)]
    env.sheet("06/2026").transactions.update_faults = [PASS, ("before", Crash())]
    upload_id = await crash_upload(env, rows)
    assert len(env.block_rows("06/2026", EXPENSES)) == 2 and env.block_rows("06/2026", INCOME) == []
    await env.pipeline().resume()
    assert len(env.block_rows("06/2026", EXPENSES)) == 2
    assert len(env.block_rows("06/2026", INCOME)) == 1
    assert env.period(upload_id, "06/2026")["reconcile"] == {"expenses": "positional", "income": "positional"}


async def test_write_error_after_the_expense_block_landed_resume_writes_only_income(tmp_path):
    env = Env(tmp_path)
    rows = [row("10-06-2026"), row("11-06-2026"), income(12)]
    ws = env.sheet("06/2026").transactions
    ws.update_faults = [PASS, ("before", FakeHttpError(503))]
    upload_id, report = await env.upload(rows)          # an ordinary error: the run finishes
    assert env.period(upload_id, "06/2026")["status"] == "appending"
    await env.pipeline().resume()
    assert len(env.block_rows("06/2026", EXPENSES)) == 2
    assert len(env.block_rows("06/2026", INCOME)) == 1
    assert env.period(upload_id, "06/2026")["status"] == "written"


async def test_reconcile_on_an_empty_block_appends_at_the_data_start_row(tmp_path):
    env = Env(tmp_path)
    ws = env.sheet("06/2026").transactions
    ws.update_faults = [("before", Crash())]
    await crash_upload(env, [row("10-06-2026")])
    await env.pipeline().resume()
    assert [c[1] for c in ws.updates()][0] == "B5:E5"


async def test_after_reconciliation_record_written_covers_every_row_exactly_once(tmp_path):
    env = Env(tmp_path)
    rows = [row("10-06-2026"), row("11-06-2026"), income(12)]
    env.sheet("06/2026").transactions.update_faults = [PASS, ("before", Crash())]
    upload_id = await crash_upload(env, rows)
    await env.pipeline().resume()
    data = env.ledger()._load()
    recorded = {k: e["labels"]["06/2026"][upload_id] for k, e in data["strong"].items()}
    assert recorded == {strong_key_of(r): 1 for r in rows}


# ── commit order ─────────────────────────────────────────────────────────────

async def test_crash_after_the_audit_before_the_flip_appends_nothing_and_a_reupload_writes_zero(tmp_path):
    env = Env(tmp_path)
    rows = [row("10-06-2026"), income(12)]
    ledger = CrashingLedger(env.ledger_path, "record_audit", nth=2, after=True)
    upload_id = await crash_upload(env, rows, ledger=ledger)
    assert env.period(upload_id, "06/2026")["status"] == "appending"
    assert env.written("06/2026") == 2
    await env.pipeline().resume()
    assert env.written("06/2026") == 2
    await env.upload(rows)
    assert env.written("06/2026") == 2


async def test_crash_before_record_written_appends_everything_once(tmp_path):
    env = Env(tmp_path)
    rows = [row("10-06-2026"), row("11-06-2026"), income(12)]
    upload_id = await crash_upload(env, rows, ledger=CrashingLedger(env.ledger_path, "record_written"))
    assert env.written("06/2026") == 0
    await env.pipeline().resume()
    assert env.written("06/2026") == 3


async def test_crash_between_record_written_and_the_write_appends_everything_once(tmp_path):
    env = Env(tmp_path)
    rows = [row("10-06-2026"), row("11-06-2026"), income(12)]
    env.sheet("06/2026").transactions.update_faults = [("before", Crash())]
    await crash_upload(env, rows)
    assert env.ledger()._load()["strong"]                 # over-recorded, as permitted
    await env.pipeline().resume()
    assert env.written("06/2026") == 3


async def test_crash_between_commit_and_audit_audits_the_found_rows_so_undo_is_complete(tmp_path):
    env = Env(tmp_path)
    pre_rows(env, [(1, 3.0, "a"), (2, 4.0, "b")])
    before = as_tuples(env)
    rows = [row("10-06-2026"), row("11-06-2026"), income(12)]
    upload_id = await crash_upload(env, rows, ledger=CrashingLedger(env.ledger_path, "record_audit"))
    assert env.ledger().audited_rows(upload_id) == {}
    await env.pipeline().resume()
    audited = env.ledger().audited_rows(upload_id)
    sh = env.sheet("06/2026")
    for block in (EXPENSES, INCOME):
        removed, not_found = remove_rows(sh, block, audited[sh.id][block.name], is_appending=NOT_APPENDING)
        assert not_found == 0
    assert as_tuples(env) == before and env.block_rows("06/2026", INCOME) == []


# ── the fallback ─────────────────────────────────────────────────────────────

async def test_a_sort_between_crash_and_resume_takes_the_fallback_not_the_positional_path(tmp_path):
    env = Env(tmp_path)
    pre_rows(env, [(20, 3.0, "a"), (21, 4.0, "b"), (22, 5.0, "c")])
    rows = [row("10-06-2026"), row("11-06-2026"), income(12)]
    sh = env.sheet("06/2026")
    sh.transactions.update_faults = [("after", Crash())]          # expenses land, then the process dies
    upload_id = await crash_upload(env, rows)
    count = len(read_block(sh, EXPENSES).tuples)
    sort_by_date(sh, is_appending=NOT_APPENDING)                  # the user sorts by hand meanwhile
    assert len(read_block(sh, EXPENSES).tuples) == count          # a row count cannot see the sort
    report = await env.pipeline().resume()
    period = env.period(upload_id, "06/2026")
    assert period["reconcile"] == {"expenses": "fallback", "income": "positional"}
    assert len(env.block_rows("06/2026", EXPENSES)) == 5          # nothing appended twice
    assert len(env.block_rows("06/2026", INCOME)) == 1
    assert period["partial_undo"] and "partial" in report.text


async def test_the_fallback_audits_only_what_it_appended(tmp_path):
    env = Env(tmp_path)
    pre_rows(env, [(20, 3.0, "a"), (21, 4.0, "b")])
    rows = [row("10-06-2026"), income(12)]
    sh = env.sheet("06/2026")
    sh.transactions.update_faults = [("after", Crash())]
    upload_id = await crash_upload(env, rows)
    sort_by_date(sh, is_appending=NOT_APPENDING)
    await env.pipeline().resume()
    audited = env.ledger().audited_rows(upload_id)[sh.id]
    assert "expenses" not in audited                              # found by content: never audited
    assert len(audited["income"]) == 1


async def test_fallback_drops_an_intended_row_equal_to_a_preexisting_one_and_says_so(tmp_path):
    env = Env(tmp_path)
    tx, other = row("10-06-2026", amount="-11.25", seq="X2"), row("11-06-2026")
    pre_rows(env, [(25, 3.0, "a"), (10, 11.25, "Desc X2")])       # unsorted, and equal to tx
    sh = env.sheet("06/2026")
    sh.transactions.update_faults = [("before", Crash())]
    upload_id = await crash_upload(env, [tx, other])
    sort_by_date(sh, is_appending=NOT_APPENDING)
    report = await env.pipeline().resume()
    assert env.period(upload_id, "06/2026")["reconcile"]["expenses"] == "fallback"
    assert Counter(as_tuples(env))[sheet_row(tx)] == 1            # the known weakness: dropped
    assert sheet_row(other) in as_tuples(env)
    assert "fallback" in report.text and "row count" in report.text


async def test_the_fallback_appends_after_the_current_last_row_and_keeps_live_data(tmp_path):
    env = Env(tmp_path)
    pre_rows(env, [(25, 3.0, "a"), (5, 4.0, "b"), (15, 5.0, "c")])
    sh = env.sheet("06/2026")
    sh.transactions.update_faults = [("before", Crash())]
    rows = [row("10-06-2026"), row("11-06-2026")]
    await crash_upload(env, rows)
    sort_by_date(sh, is_appending=NOT_APPENDING)
    sh.transactions.put("B8", [[serial(date(2026, 6, 28)), 9.0, "by hand", "Boodschappen"]])
    await env.pipeline().resume()
    appends = [c[1] for c in sh.transactions.updates() if c[2] == "USER_ENTERED"]
    assert appends == ["B9:E10"]                  # after the current last row, not at first_write_row (8)
    got = as_tuples(env)
    assert len(got) == 6
    assert {t[2] for t in got} >= {"a", "b", "c", "by hand"}


# ── index partition, not tuple membership ────────────────────────────────────

async def test_one_of_two_identical_rows_landed_writes_one_audits_two_and_undo_removes_two(tmp_path):
    env = Env(tmp_path)
    pre_rows(env, [(1, 3.0, "a")])
    before = as_tuples(env)
    twins = [row("10-06-2026", amount="-5.00", remittance="SAME"),
             row("10-06-2026", amount="-5.00", remittance="SAME")]
    sh = env.sheet("06/2026")
    sh.transactions.update_faults = [("before", Crash())]
    upload_id = await crash_upload(env, twins)
    sh.transactions.put("B6", [[serial(date(2026, 6, 10)), 5.0, "Same", "Boodschappen"]])   # one landed
    await env.pipeline().resume()
    assert Counter(as_tuples(env))[sheet_row(twins[0], "Same")] == 2
    audited = env.ledger().audited_rows(upload_id)[sh.id]["expenses"]
    assert len(audited) == 2
    removed, not_found = remove_rows(sh, EXPENSES, audited, is_appending=NOT_APPENDING)
    assert (removed, not_found) == (2, 0)
    assert as_tuples(env) == before


async def test_reconcile_records_the_same_strong_keys_as_a_first_attempt(tmp_path):
    rows = [row("10-06-2026"), row("11-06-2026", remittance="SAME"), income(12)]
    clean = Env(tmp_path / "a")
    await clean.upload(rows)
    crashed = Env(tmp_path / "b")
    crashed.sheet("06/2026").transactions.update_faults = [PASS, ("before", Crash())]
    await crash_upload(crashed, rows)
    await crashed.pipeline().resume()
    assert set(clean.ledger()._load()["strong"]) == set(crashed.ledger()._load()["strong"])


def strong_key_of(asn):
    """The ledger key of a synthetic export row, via the same loader the pipeline uses."""
    import csv
    import os
    import tempfile
    from finance_core.csv_helper import load_transactions_from_csv
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "one.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(asn)
        return strong_key(load_transactions_from_csv(path)[0])
