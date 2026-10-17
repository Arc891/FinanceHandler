"""
Tests for src/cli.py: the Discord-free `finance age` command (spec Decision 5,
amendment 5a in docs/ingest-notes.md).

Every fixture is a synthetic run file under tmp_path; nothing reads data/.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import cli

SRC = os.path.dirname(os.path.realpath(cli.__file__))
CLI_PATH = os.path.join(SRC, "cli.py")

NOW = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)


# ── fixtures ────────────────────────────────────────────────────────────────

def period(label, status, expenses=1, income=0, counts=True):
    p = {"label": label, "status": status,
         "rows": {"expenses": [{"x": i} for i in range(expenses)],
                  "income": [{"x": i} for i in range(income)]}}
    if counts:
        p["counts"] = {"rows": expenses + income, "expenses": expenses, "income": income}
    return p


def write_run(runs_dir, upload_id, *, closed=None, closed_at=None, started_at="2026-01-01T00:00:00+00:00",
              periods=()):
    runs_dir.mkdir(parents=True, exist_ok=True)
    run = {"upload_id": upload_id, "files": ["synthetic.csv"], "started_at": started_at,
           "closed": closed, "closed_at": closed_at, "periods": list(periods)}
    (runs_dir / f"{upload_id}.json").write_text(json.dumps(run), encoding="utf-8")


def write_ledger(path, runs):
    path.write_text(json.dumps({"version": 1, "strong": {}, "seeded": {}, "runs": runs}), encoding="utf-8")


def run_age(tmp_path, capsys, *, json_out=True, now=NOW, runs_dir=None, ledger=None):
    argv = ["age", "--runs-dir", str(runs_dir or tmp_path / "runs"),
            "--ledger", str(ledger or tmp_path / "upload_ledger.json")]
    if json_out:
        argv.append("--json")
    code = cli.main(argv, now=now)
    out, err = capsys.readouterr()
    return code, out, err


def assert_fixture(runs_dir):
    assert list(runs_dir.glob("*.json")), "fixture has no run files"


# ── the JSON contract ──────────────────────────────────────────────────────

def test_json_has_exactly_the_two_contract_keys(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "u1", closed="complete", closed_at="2026-10-10T08:00:00+00:00")
    assert_fixture(runs)

    code, out, err = run_age(tmp_path, capsys)

    assert code == 0
    assert err == ""
    lines = out.splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert list(data) == ["days_since_last_statement", "pending_review_rows"]
    assert lines[0] == '{"days_since_last_statement": 7, "pending_review_rows": 0}'


def test_fresh_run_reports_days_since_newest_complete_run(tmp_path, capsys):
    runs = tmp_path / "runs"
    # started order differs from closed order: the newest close wins
    write_run(runs, "old", closed="complete", started_at="2026-10-01T00:00:00+00:00",
              closed_at="2026-10-15T09:00:00+00:00")
    write_run(runs, "older", closed="complete", started_at="2026-10-02T00:00:00+00:00",
              closed_at="2026-10-03T09:00:00+00:00")
    assert_fixture(runs)

    code, out, _ = run_age(tmp_path, capsys)

    assert code == 0
    assert json.loads(out) == {"days_since_last_statement": 2, "pending_review_rows": 0}

    code, out, _ = run_age(tmp_path, capsys, json_out=False)
    assert code == 0
    assert out == "last statement imported 2 days ago (2026-10-15); 0 rows pending in open runs\n"


def test_stale_run_exits_zero_and_reports_the_age(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "u1", closed="complete", closed_at="2026-08-01T12:00:00+00:00")
    assert_fixture(runs)

    code, out, err = run_age(tmp_path, capsys)

    assert code == 0
    assert err == ""
    assert json.loads(out)["days_since_last_statement"] == 77


def test_no_runs_dir_prints_null_days_and_zero_pending(tmp_path, capsys):
    assert not (tmp_path / "runs").exists()

    code, out, err = run_age(tmp_path, capsys)

    assert code == 0
    assert err == ""
    assert out == '{"days_since_last_statement": null, "pending_review_rows": 0}\n'

    code, out, _ = run_age(tmp_path, capsys, json_out=False)
    assert code == 0
    assert out == "no imported statement on record; 0 rows pending in open runs\n"


def test_open_abandoned_and_refused_runs_are_not_a_statement(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "open", closed=None, periods=[period("10/2026", "written")])
    write_run(runs, "abandoned", closed="abandoned", closed_at="2026-10-16T08:00:00+00:00")
    write_run(runs, "refused", closed="refused", closed_at="2026-10-16T09:00:00+00:00")
    assert_fixture(runs)

    code, out, _ = run_age(tmp_path, capsys)

    assert code == 0
    assert json.loads(out) == {"days_since_last_statement": None, "pending_review_rows": 0}

    write_run(runs, "done", closed="complete", closed_at="2026-10-07T08:00:00+00:00")
    code, out, _ = run_age(tmp_path, capsys)
    assert json.loads(out)["days_since_last_statement"] == 10


def test_undone_run_is_not_a_statement(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "kept", closed="complete", closed_at="2026-10-05T08:00:00+00:00")
    write_run(runs, "undone", closed="complete", closed_at="2026-10-16T08:00:00+00:00")
    assert_fixture(runs)
    write_ledger(tmp_path / "upload_ledger.json", {
        "kept": {"anchor_before": None, "started_at": None, "undone_at": None, "sheets": {}},
        "undone": {"anchor_before": None, "started_at": None,
                   "undone_at": "2026-10-16T20:00:00+00:00", "sheets": {}},
    })

    code, out, _ = run_age(tmp_path, capsys)

    assert code == 0
    assert json.loads(out)["days_since_last_statement"] == 12

    write_ledger(tmp_path / "upload_ledger.json", {
        "kept": {"undone_at": "2026-10-16T20:00:00+00:00"},
        "undone": {"undone_at": "2026-10-16T20:00:00+00:00"},
    })
    code, out, _ = run_age(tmp_path, capsys)
    assert json.loads(out)["days_since_last_statement"] is None


def test_pending_rows_sum_unwritten_periods_of_open_runs(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "open1", closed=None, periods=[
        period("09/2026", "written", expenses=50),            # written: not pending
        period("10/2026", "appending", expenses=3, income=2),  # 5
        period("11/2026", "failed", expenses=1),               # 1
    ])
    write_run(runs, "open2", closed=None, started_at="2026-10-16T00:00:00+00:00", periods=[
        period("10/2026", "categorised", expenses=4, income=1, counts=False),  # 5 via len(rows)
    ])
    write_run(runs, "closed", closed="abandoned", closed_at="2026-10-16T00:00:00+00:00", periods=[
        period("10/2026", "split", expenses=99),  # closed run: not pending
    ])
    assert_fixture(runs)

    code, out, _ = run_age(tmp_path, capsys)

    assert code == 0
    assert json.loads(out) == {"days_since_last_statement": None, "pending_review_rows": 11}

    code, out, _ = run_age(tmp_path, capsys, json_out=False)
    assert out == "no imported statement on record; 11 rows pending in open runs\n"


def test_day_boundary_is_europe_amsterdam(tmp_path, capsys):
    runs = tmp_path / "runs"
    # 22:30 UTC on 4 Oct is 00:30 CEST on 5 Oct
    write_run(runs, "summer", closed="complete", closed_at="2026-10-04T22:30:00+00:00")
    assert_fixture(runs)

    code, out, _ = run_age(tmp_path, capsys, now=datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc))
    assert code == 0
    assert json.loads(out)["days_since_last_statement"] == 0

    code, out, _ = run_age(tmp_path, capsys, json_out=False,
                           now=datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc))
    assert "(2026-10-05)" in out

    # winter time: 23:30 UTC on 10 Jan is 00:30 CET on 11 Jan; now 22:30 UTC on 11 Jan is 23:30 CET
    winter = tmp_path / "winter"
    write_run(winter, "w", closed="complete", closed_at="2026-01-10T23:30:00+00:00")
    assert_fixture(winter)
    code, out, _ = run_age(tmp_path, capsys, runs_dir=winter,
                           now=datetime(2026, 1, 11, 22, 30, tzinfo=timezone.utc))
    assert json.loads(out)["days_since_last_statement"] == 0
    # and 23:30 UTC on 11 Jan is already 12 Jan in Amsterdam
    code, out, _ = run_age(tmp_path, capsys, runs_dir=winter,
                           now=datetime(2026, 1, 11, 23, 30, tzinfo=timezone.utc))
    assert json.loads(out)["days_since_last_statement"] == 1


def test_naive_closed_at_is_utc_and_future_is_clamped_to_zero(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "naive", closed="complete", closed_at="2026-10-04T22:30:00")
    assert_fixture(runs)
    code, out, _ = run_age(tmp_path, capsys, now=datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc))
    assert json.loads(out)["days_since_last_statement"] == 0

    write_run(runs, "future", closed="complete", closed_at="2026-10-20T08:00:00+00:00")
    code, out, err = run_age(tmp_path, capsys)
    assert code == 0
    assert err == ""
    assert json.loads(out)["days_since_last_statement"] == 0


# ── unreadable state ───────────────────────────────────────────────────────

def test_unreadable_run_file_prints_nulls_and_exits_zero(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "good", closed="complete", closed_at="2026-10-10T08:00:00+00:00")
    (runs / "broken.json").write_text("{not json", encoding="utf-8")
    assert_fixture(runs)

    code, out, err = run_age(tmp_path, capsys)

    assert code == 0
    assert out == '{"days_since_last_statement": null, "pending_review_rows": null}\n'
    assert err == "finance age: unreadable run state\n"
    assert str(tmp_path) not in err and "Traceback" not in err

    # an unreadable ledger is the same state
    (runs / "broken.json").unlink()
    (tmp_path / "upload_ledger.json").write_text("[", encoding="utf-8")
    code, out, err = run_age(tmp_path, capsys)
    assert code == 0
    assert out == '{"days_since_last_statement": null, "pending_review_rows": null}\n'
    assert err == "finance age: unreadable run state\n"

    code, out, err = run_age(tmp_path, capsys, json_out=False)
    assert code == 0
    assert err == "finance age: unreadable run state\n"
    assert "broken" not in out and str(tmp_path) not in out


def test_plain_output_never_shows_ids_files_or_rows(tmp_path, capsys):
    runs = tmp_path / "runs"
    write_run(runs, "upload-SECRETID", closed="complete", closed_at="2026-10-10T08:00:00+00:00")
    write_run(runs, "open-SECRETID", closed=None, periods=[period("10/2026", "split", expenses=2)])
    assert_fixture(runs)

    code, out, _ = run_age(tmp_path, capsys, json_out=False)

    assert code == 0
    assert "SECRETID" not in out and "synthetic" not in out
    assert out == "last statement imported 7 days ago (2026-10-10); 2 rows pending in open runs\n"


# ── process level ──────────────────────────────────────────────────────────

def test_import_does_not_load_discord_or_google():
    code = ("import sys; sys.path.insert(0, %r); import cli; "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('discord', 'google', 'googleapiclient')]; "
            "assert not bad, bad; print('ok')") % SRC
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_runs_through_a_symlink_with_system_python(tmp_path):
    assert os.access(CLI_PATH, os.X_OK), "src/cli.py is not executable"
    with open(CLI_PATH, encoding="utf-8") as fh:
        assert fh.readline() == "#!/usr/bin/env python3\n"

    runs = tmp_path / "runs"
    write_run(runs, "open", closed=None, periods=[period("10/2026", "resolved", expenses=2, income=1)])
    assert_fixture(runs)
    link_dir = tmp_path / "bin"
    link_dir.mkdir()
    link = link_dir / "finance"
    link.symlink_to(CLI_PATH)

    proc = subprocess.run(
        ["env", "-i", "PATH=/usr/bin:/bin", str(link), "age", "--json",
         "--runs-dir", str(runs), "--ledger", str(tmp_path / "upload_ledger.json")],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path))

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    assert proc.stdout == '{"days_since_last_statement": null, "pending_review_rows": 3}\n'


def test_ingest_stub_says_not_implemented(capsys):
    code = cli.main(["ingest"])
    out, err = capsys.readouterr()
    assert code == 1
    assert out == ""
    assert err == "finance ingest: not implemented yet, see ~/Coding/specs/finance-ingest.md step 5\n"

    with pytest.raises(SystemExit) as exc:
        cli.main(["no-such-command"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
