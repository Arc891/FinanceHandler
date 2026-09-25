"""
Tests for finance_core.export.Pipeline (plan 4.7, section 5 test_process_upload.py).

Fakes only: FakeWorkbooks for Google, FakeEngine for the categoriser. The
invariant every test comes back to: rows written equals rows accepted, across
however many runs and resumes it takes.
"""

import asyncio
import csv
import os
from datetime import date

import pytest

from fakes import FakeHttpError, serial
from pipeline_env import Crash, Env, duo, row, three_boundary_rows

from finance_core import export
from finance_core.google_auth import GoogleAuthError
from finance_core.period_state import load_anchor
from finance_core.periods import split_into_periods
from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.sheet_index import load_index

PLACEHOLDER = "! Nog in te delen !"


def statuses(env, upload_id):
    return {p["label"]: p["status"] for p in env.run(upload_id)["periods"]}


# ── the happy path ───────────────────────────────────────────────────────────

async def test_three_boundaries_write_four_sheets_and_every_accepted_row(tmp_path):
    env = Env(tmp_path)
    rows = three_boundary_rows()
    upload_id, report = await env.upload(rows)

    assert statuses(env, upload_id) == {l: "written" for l in ("06/2026", "07/2026", "08/2026", "09/2026")}
    index = load_index(env.index_path)
    assert [l for l in ("07/2026", "08/2026", "09/2026") if index[l]["created_by_bot"]] == \
        ["07/2026", "08/2026", "09/2026"]
    assert {l: env.written(l) for l in index} == {"06/2026": 4, "07/2026": 6, "08/2026": 4, "09/2026": 3}
    assert env.total_written() == len(rows)
    assert report.complete
    assert env.run(upload_id)["closed"] == "complete"


async def test_per_sheet_counts_equal_the_splitters(tmp_path):
    env = Env(tmp_path)
    rows = three_boundary_rows()
    upload_id, _ = await env.upload(rows)
    run = env.run(upload_id)
    expected = {p["label"]: p["counts"]["rows"] for p in run["periods"]}
    assert expected == {l: env.written(l) for l in expected}
    assert load_anchor(env.state_path).label == "09/2026"


async def test_fixture_export_writes_rows_written_equal_to_rows_accepted(tmp_path):
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "multi_month.csv")
    env = Env(tmp_path, anchor=("24-05-2026", "06/2026"))
    with open(fixture, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    upload_id, report = await env.upload(rows)
    run = env.run(upload_id)
    assert [p["label"] for p in run["periods"]] == ["06/2026", "07/2026", "08/2026", "09/2026", "10/2026"]
    assert all(p["status"] == "written" for p in run["periods"])
    assert env.total_written() == run["notes"]["accepted"] == 390


async def test_second_identical_upload_writes_zero(tmp_path):
    env = Env(tmp_path)
    rows = three_boundary_rows()
    await env.upload(rows)
    before = env.total_written()
    upload_id, report = await env.upload(rows)
    assert env.total_written() == before
    assert env.run(upload_id)["periods"] == []
    assert env.run(upload_id)["closed"] == "complete"
    assert f"{len(rows)} already uploaded" in report.text


async def test_flagged_rows_carry_the_placeholder_and_their_guess_reaches_the_summary(tmp_path):
    env = Env(tmp_path)
    rows = [row("10-06-2026", remittance="FLAG etentje", seq="777"), row("11-06-2026")]
    upload_id, report = await env.upload(rows)
    cats = [r[3] for r in env.block_rows("06/2026", EXPENSES)]
    assert cats.count(PLACEHOLDER) == 1
    assert "Guess 777" in report.text and "Uit eten" in report.text and "0.40" in report.text
    flagged = env.run(upload_id)["periods"][0]["flagged"]
    assert [(f["ai_category"], f["ai_confidence"]) for f in flagged] == [("Uit eten", 0.4)]


async def test_flagged_lines_beyond_the_cap_go_to_an_attachment(tmp_path):
    env = Env(tmp_path, summary_flagged_lines=3)
    rows = [row(f"{10 + i}-06-2026", remittance=f"FLAG {i}") for i in range(5)]
    _, report = await env.upload(rows)
    assert report.text.count("Uit eten (0.40)") == 3
    assert "2 more" in report.text
    assert report.flagged_attachment.count("Uit eten (0.40)") == 5


# ── failures that leave rows owed ───────────────────────────────────────────

async def test_refused_copy_fails_that_period_only_and_resume_writes_its_rows(tmp_path):
    env = Env(tmp_path)
    rows = three_boundary_rows()

    def refuse_next_create(label):
        if label == "08/2026":                     # categorised just before 09/2026 is resolved
            env.wb.faults["copy_tab"] = [FakeHttpError(403)]
    env.engine.before_call = refuse_next_create

    upload_id, report = await env.upload(rows)
    assert statuses(env, upload_id) == {"06/2026": "written", "07/2026": "written",
                                        "08/2026": "written", "09/2026": "failed"}
    held = env.period(upload_id, "09/2026")["rows"]
    assert len(held["expenses"]) + len(held["income"]) == 3
    assert not report.complete and "09/2026" in report.text and "failed" in report.text
    assert os.path.isdir(env.uploads_dir / upload_id)

    env.engine.before_call = None
    report = await env.pipeline().resume()
    assert statuses(env, upload_id)["09/2026"] == "written"
    assert env.total_written() == len(rows)
    assert report.complete
    assert not os.path.exists(env.uploads_dir / upload_id)


async def test_auth_error_stops_the_run_and_resume_writes_the_rest(tmp_path):
    env = Env(tmp_path)
    rows = three_boundary_rows()

    def lose_auth(label):
        if label == "07/2026":
            env.wb.faults["create_workbook"] = [GoogleAuthError("token revoked")]
    env.engine.before_call = lose_auth

    upload_id, report = await env.upload(rows)
    assert statuses(env, upload_id) == {"06/2026": "written", "07/2026": "written",
                                        "08/2026": "split", "09/2026": "split"}
    for label in ("08/2026", "09/2026"):
        held = env.period(upload_id, label)["rows"]
        assert held["expenses"] or held["income"]
    assert "google_login" in report.text or "authoris" in report.text
    assert not report.complete

    env.engine.before_call = None
    await env.pipeline().resume(upload_id)
    assert env.total_written() == len(rows)


async def test_uploaded_files_survive_until_every_period_is_written(tmp_path):
    env = Env(tmp_path)
    env.engine.before_call = lambda label: (label == "08/2026"
                                            and env.wb.faults.update(copy_tab=[FakeHttpError(403)]))
    upload_id, _ = await env.upload(three_boundary_rows())
    assert os.path.isdir(env.uploads_dir / upload_id)
    env.engine.before_call = None
    await env.pipeline().resume()
    assert not os.path.exists(env.uploads_dir / upload_id)


# ── the AI budget ────────────────────────────────────────────────────────────

async def test_deadline_passed_to_the_engine_is_the_run_budget(tmp_path):
    env = Env(tmp_path, ai_run_max_minutes=30.0)
    start = env.clock()
    await env.upload(three_boundary_rows())
    assert {d for _, _, d in env.engine.calls} == {start + 30 * 60}


async def test_budget_trip_write_flagged_writes_the_remainder_flagged(tmp_path):
    env = Env(tmp_path, ai_run_max_minutes=1.0, budget_trip_action="write_flagged")
    env.engine.spend["07/2026"] = 120.0
    rows = three_boundary_rows()
    upload_id, report = await env.upload(rows)
    assert set(statuses(env, upload_id).values()) == {"written"}
    assert env.total_written() == len(rows)
    for label in ("07/2026", "08/2026", "09/2026"):
        assert {r[3] for r in env.block_rows(label, EXPENSES)} == {PLACEHOLDER}
    assert {r[3] for r in env.block_rows("06/2026", EXPENSES)} == {"Boodschappen"}
    assert "budget" in report.text


async def test_budget_trip_stop_leaves_unstarted_periods_for_resume(tmp_path):
    env = Env(tmp_path, ai_run_max_minutes=1.0, budget_trip_action="stop")
    env.engine.spend["07/2026"] = 120.0
    rows = three_boundary_rows()
    upload_id, report = await env.upload(rows)
    st = statuses(env, upload_id)
    # the tripping period finishes under write_flagged semantics: every row has a category
    assert st["07/2026"] == "written"
    assert {r[3] for r in env.block_rows("07/2026", EXPENSES)} == {PLACEHOLDER}
    assert all(r[3] for r in env.block_rows("07/2026", INCOME))
    # un-started periods are held, uncategorised, so /resume categorises them
    assert st["08/2026"] == st["09/2026"] == "split"
    assert not env.period(upload_id, "08/2026")["categorised"]
    assert "08/2026" in report.text and "budget" in report.text and not report.complete
    assert [c[0] for c in env.engine.calls] == ["06/2026", "07/2026"]

    env.engine.spend.clear()
    await env.pipeline().resume()
    assert set(statuses(env, upload_id).values()) == {"written"}
    assert {r[3] for r in env.block_rows("08/2026", EXPENSES)} == {"Boodschappen"}
    assert env.total_written() == len(rows)


# ── resume ───────────────────────────────────────────────────────────────────

async def test_resume_on_appending_writes_only_the_missing_rows(tmp_path):
    env = Env(tmp_path)
    env.wb.books["id-06-2026"].transactions.update_faults = [("before", Crash())]
    rows = [row("10-06-2026"), row("11-06-2026"), row("12-06-2026", amount="20.00")]
    with pytest.raises(Crash):
        await env.upload(rows)
    upload_id = env.pipeline().store.open_runs()[-1]["upload_id"]
    assert statuses(env, upload_id) == {"06/2026": "appending"}
    await env.pipeline().resume()
    assert env.written("06/2026") == 3
    assert statuses(env, upload_id) == {"06/2026": "written"}


async def test_resume_on_appending_writes_nothing_when_the_append_had_landed(tmp_path):
    env = Env(tmp_path)
    ws = env.wb.books["id-06-2026"].transactions
    ws.update_faults = [("after", Crash())]
    rows = [row("10-06-2026"), row("11-06-2026")]
    with pytest.raises(Crash):
        await env.upload(rows)
    assert env.written("06/2026") == 2
    updates = len(ws.updates())
    await env.pipeline().resume()
    assert env.written("06/2026") == 2
    assert len(ws.updates()) == updates            # the closing sort had nothing to reorder


async def test_resume_on_categorised_reresolves_without_resplitting_or_recategorising(tmp_path, monkeypatch):
    env = Env(tmp_path)
    real = export.plan_append

    def crash_once(*a, **k):
        monkeypatch.setattr(export, "plan_append", real)
        raise Crash()
    monkeypatch.setattr(export, "plan_append", crash_once)
    rows = [row("10-06-2026"), row("11-06-2026")]
    with pytest.raises(Crash):
        await env.upload(rows)
    upload_id = env.pipeline().store.open_runs()[-1]["upload_id"]
    assert statuses(env, upload_id) == {"06/2026": "categorised"}

    splits = []
    monkeypatch.setattr(export, "split_into_periods", lambda *a, **k: splits.append(1) or split_into_periods(*a, **k))
    calls = len(env.engine.calls)
    await env.pipeline().resume()
    assert splits == [] and len(env.engine.calls) == calls
    assert env.written("06/2026") == 2
    assert {r[2] for r in env.block_rows("06/2026", EXPENSES)} <= {f"Desc {r[15]}" for r in rows}


async def test_resume_picks_the_newest_open_run_and_honours_an_explicit_id(tmp_path):
    env = Env(tmp_path)
    for rows in ([row("10-06-2026")], [row("11-06-2026")]):
        env.wb.faults["open"] = [FakeHttpError(404)]       # resolution fails: both runs stay open
        await env.upload(rows)
    runs = env.pipeline().store.open_runs()
    assert len(runs) == 2
    older, newer = runs[0]["upload_id"], runs[1]["upload_id"]
    report = await env.pipeline().resume()
    assert report.upload_id == newer
    assert statuses(env, older) == {"06/2026": "failed"}
    report = await env.pipeline().resume(older)
    assert report.upload_id == older and statuses(env, older) == {"06/2026": "written"}


async def test_crash_before_the_split_is_rerun_from_the_start_and_never_reported_as_success(tmp_path, monkeypatch):
    env = Env(tmp_path)
    monkeypatch.setattr(export, "split_into_periods", lambda *a, **k: (_ for _ in ()).throw(Crash()))
    rows = three_boundary_rows()
    with pytest.raises(Crash):
        await env.upload(rows)
    upload_id = env.pipeline().store.open_runs()[-1]["upload_id"]
    assert env.run(upload_id)["periods"] == []
    monkeypatch.setattr(export, "split_into_periods", split_into_periods)
    report = await env.pipeline().resume()
    assert report.upload_id == upload_id and report.complete
    assert env.total_written() == len(rows)


# ── refusals ─────────────────────────────────────────────────────────────────

async def _appending_run(env):
    env.wb.books["id-06-2026"].transactions.update_faults = [("before", FakeHttpError(503))]
    upload_id, report = await env.upload([row("10-06-2026"), row("11-06-2026")])
    assert statuses(env, upload_id) == {"06/2026": "appending"}
    return upload_id, report


async def test_write_failure_leaves_the_period_appending_and_the_run_continues(tmp_path):
    env = Env(tmp_path)
    rows = three_boundary_rows()
    seen = {}

    def fault_07(label):
        if label == "07/2026":                     # resolved (created) just before this call
            sid = load_index(env.index_path)["07/2026"]["id"]
            ws = env.wb.books[sid].transactions
            ws.update_faults = [("before", FakeHttpError(503))]
            seen.update(ws=ws, n=len(ws.updates()))
    env.engine.before_call = fault_07
    upload_id, report = await env.upload(rows)
    st = statuses(env, upload_id)
    assert st["07/2026"] == "appending" and env.period(upload_id, "07/2026")["last_error"]
    assert st["06/2026"] == st["08/2026"] == st["09/2026"] == "written"
    assert "07/2026: left unsorted pending /resume" in report.text
    assert "Sort:" not in report.text             # skipped on purpose, not refused by the writer's guard
    # the closing sort skipped 07's sheet only: nothing was written there after the fault
    assert seen["ws"].updates()[seen["n"]:] == []

    env.engine.before_call = None
    await env.pipeline().resume()
    assert env.period(upload_id, "07/2026")["status"] == "written"
    assert env.period(upload_id, "07/2026")["reconcile"] == {"expenses": "positional", "income": "positional"}
    assert env.total_written() == len(rows)


async def test_upload_refuses_while_any_open_run_has_an_appending_period(tmp_path):
    env = Env(tmp_path)
    upload_id, _ = await _appending_run(env)
    with pytest.raises(export.RunRefused) as exc:
        await env.upload([row("12-06-2026")])
    assert upload_id in str(exc.value) and "06/2026" in str(exc.value) and "/resume" in str(exc.value)


async def test_a_second_upload_during_a_run_is_refused(tmp_path):
    env = Env(tmp_path)
    gate = asyncio.Event()
    entered = asyncio.Event()
    pipeline = env.pipeline()

    async def slow(transactions, deadline=None, **kw):
        entered.set()
        await gate.wait()
        return await type(env.engine).batch_categorize(env.engine, transactions, deadline)
    env.engine.batch_categorize = slow

    first = asyncio.create_task(env.upload([row("10-06-2026")], pipeline=pipeline))
    await entered.wait()
    try:
        with pytest.raises(export.RunRefused, match="in progress"):
            await asyncio.wait_for(env.upload([row("11-06-2026")], pipeline=pipeline), timeout=5)
    finally:
        gate.set()
    await first
    assert env.written("06/2026") == 1


async def test_cancel_refuses_while_appending_and_names_resume_before_undo(tmp_path):
    env = Env(tmp_path)
    upload_id, _ = await _appending_run(env)
    with pytest.raises(export.RunRefused) as exc:
        env.pipeline().cancel(upload_id, confirm=True)
    msg = str(exc.value)
    assert "06/2026" in msg and msg.index("/resume") < msg.index("undo_upload.py")


async def test_cancel_requires_confirm_when_rows_would_be_discarded(tmp_path):
    env = Env(tmp_path)
    env.wb.faults["open"] = [FakeHttpError(404)]
    upload_id, _ = await env.upload([row("10-06-2026"), row("11-06-2026")])
    assert statuses(env, upload_id) == {"06/2026": "failed"}
    with pytest.raises(export.RunRefused, match="2 rows"):
        env.pipeline().cancel(upload_id)
    message = env.pipeline().cancel(upload_id, confirm=True)
    assert "2 rows" in message
    assert env.run(upload_id)["closed"] == "abandoned"
    assert env.pipeline().store.open_runs() == []
    assert not os.path.exists(env.uploads_dir / upload_id)


async def test_sort_refuses_while_a_period_is_appending(tmp_path):
    env = Env(tmp_path)
    await _appending_run(env)
    with pytest.raises(export.RunRefused, match="appending"):
        await env.pipeline().sort()


async def test_sort_defaults_to_the_sheets_of_the_last_run(tmp_path):
    env = Env(tmp_path)
    await env.upload(three_boundary_rows())
    ws = env.sheet("06/2026").transactions
    ws.put("B9", [[serial(date(2026, 6, 1)), 1.0, "early", "Boodschappen"]])
    lines = await env.pipeline().sort()
    assert len(lines) == 4
    assert env.block_rows("06/2026", EXPENSES)[0][2] == "early"


# ── the summary ──────────────────────────────────────────────────────────────

async def test_unparsable_date_drops_the_row_and_reports_file_and_row(tmp_path):
    env = Env(tmp_path)
    bad = row("2026/06/12")
    upload_id, report = await env.upload([row("10-06-2026"), bad, row("11-06-2026")])
    assert env.written("06/2026") == 2
    assert "export1.csv row 2" in report.text


async def test_summary_and_status_name_every_period_not_written(tmp_path):
    env = Env(tmp_path)
    env.engine.before_call = lambda label: (label == "08/2026"
                                            and env.wb.faults.update(copy_tab=[FakeHttpError(403)]))
    upload_id, report = await env.upload(three_boundary_rows())
    status = env.pipeline().status()
    for text in (report.text, status):
        assert "09/2026" in text and "failed" in text and "3 rows" in text


async def test_summary_lists_periods_boundaries_creations_skips_collapses_and_flags(tmp_path):
    env = Env(tmp_path)
    first = [row("10-06-2026", seq="s1"), row("11-06-2026", seq="s2")]
    await env.upload(first)
    rows = three_boundary_rows()
    rows.append(row("26-06-2026", remittance="FLAG x"))
    overlap = rows[4:8]                                      # the same rows in a second attachment
    _, report = await env.upload(first + rows, overlap)
    text = report.text
    for label in ("06/2026", "07/2026", "08/2026", "09/2026"):
        assert label in text
    assert "24-06-2026" in text and "24-07-2026" in text and "24-08-2026" in text
    assert "created" in text
    assert "2 already uploaded" in text
    assert "4 duplicated across attachments" in text
    assert "1 flagged" in text


async def test_suspicious_split_writes_nothing_and_leaves_the_anchor(tmp_path):
    env = Env(tmp_path)
    before = open(env.state_path).read()
    far = [row("10-06-2026"), row("30-07-2026")]            # 51 days with no boundary
    upload_id, report = await env.upload(far)
    assert env.total_written() == 0
    assert open(env.state_path).read() == before
    assert env.run(upload_id)["closed"] == "refused"
    assert "nothing was written" in report.text.lower()


async def test_skipped_months_are_named(tmp_path):
    env = Env(tmp_path, months=("06/2026", "07/2026"), anchor=("24-05-2026", "06/2026"))
    rows = [row("10-06-2026"), duo("24-07-2026"), row("25-07-2026")]    # no boundary for 07/2026
    upload_id, report = await env.upload(rows, force=True)
    assert "07/2026" in report.text and "skipped" in report.text
