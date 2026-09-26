"""
Tests for scripts/seed_state.py (plan 4.3, 4.6, 4.10; section 5 spec).

The anchor history is seeded from the earliest row date of each populated
sheet, which is that month's boundary by construction; the weak ledger from
date, absolute amount and block only. Nothing is written until the user
types "yes". --set-anchor is the escape hatch of 4.3 rule 5. All data is
synthetic; the dates are section 11's measured boundaries.
"""

import json
from datetime import date

import pytest

import seed_state
from fakes import expense_tx, serial
from finance_core.period_state import load_anchor, save_anchor
from finance_core.periods import Anchor, parse_date, split_into_periods
from finance_core.run_state import RunStore
from pipeline_env import Env

SECRET = "Jolanda Vermeulen"
MONTHS = ("01/2026", "02/2026", "03/2026", "04/2026", "05/2026", "06/2026")
# label -> (expense rows, income rows) as (date, amount, description)
ROWS = {
    # earliest row in the income block
    "01/2026": ([(date(2025, 12, 27), 12.5, f"Etentje {SECRET}")],
                [(date(2025, 12, 24), 314.1, "Duo uitkering")]),
    # earliest row in the expense block; a stray late row must not matter
    "02/2026": ([(date(2026, 1, 23), 3.0, "Koffie"), (date(2026, 3, 23), 9.0, "Stray")],
                [(date(2026, 1, 25), 1800.0, "Salaris Ezra")]),
    "03/2026": ([(date(2026, 2, 24), 7.25, "Picnic"), (date(2026, 2, 24), 7.25, "Picnic")], []),
    "04/2026": ([(date(2026, 3, 23), 4.0, "Bakker")], []),
    "05/2026": ([(date(2026, 4, 24), 20.0, "Tanken")], [(date(2026, 4, 25), 314.1, "Duo")]),
    "06/2026": ([], []),                        # empty: skipped, never a null boundary
}
EXPECTED_ANCHOR = (date(2026, 4, 24), "05/2026")
EXPECTED_HISTORY = ((date(2026, 3, 23), "04/2026"), (date(2026, 2, 24), "03/2026"),
                    (date(2026, 1, 23), "02/2026"), (date(2025, 12, 24), "01/2026"))


def fill(env, rows=ROWS):
    for label, (expenses, income) in rows.items():
        ws = env.sheet(label).transactions
        if expenses:
            ws.put("B5", [[serial(d), a, desc, "Boodschappen"] for d, a, desc in expenses])
        if income:
            ws.put("G5", [[serial(d), a, desc, "DUO"] for d, a, desc in income])


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path, months=MONTHS, anchor=None)
    fill(e)
    return e


def run(env, *extra, answer="yes"):
    out, asked = [], []

    def ask(prompt):
        asked.append(prompt)
        return answer

    code = seed_state.main(
        ["--index", str(env.index_path), "--ledger", str(env.ledger_path),
         "--period-state", str(env.state_path), "--runs-dir", str(env.runs_dir), *extra],
        registry=env.registry(), stdout_write=out.append, input_fn=ask)
    return code, "".join(out), asked


def seeded(env):
    return json.loads(env.ledger_path.read_text())["seeded"]


# ── the anchor and its history ──────────────────────────────────────────────

def test_history_is_seeded_from_the_earliest_row_of_each_sheet(env):
    code, out, asked = run(env)
    assert code == 0 and asked
    anchor = load_anchor(env.state_path)
    assert (anchor.boundary, anchor.label) == EXPECTED_ANCHOR
    assert anchor.history == EXPECTED_HISTORY


def test_the_output_names_every_boundary_before_asking(env):
    _, out, _ = run(env, answer="no")
    for d, label in (EXPECTED_ANCHOR,) + EXPECTED_HISTORY:
        assert f"{d:%d-%m-%Y} -> {label}" in out


def test_an_empty_sheet_is_skipped(env):
    _, out, _ = run(env)
    assert "06/2026: no rows, skipped" in out
    assert "06/2026" not in [lbl for _, lbl in load_anchor(env.state_path).history]


def test_rule_4_places_rows_by_the_seeded_history(env):
    run(env)
    anchor = load_anchor(env.state_path)
    rows = [expense_tx(d, seq=str(i)) for i, d in enumerate(
        ("30-12-2025", "10-02-2026", "01-03-2026", "10-04-2026", "30-04-2026"))]
    result = split_into_periods(rows, anchor=anchor, markers=[r"\bDUO\b"], min_amount=250.0,
                                min_days=20, max_days=35, step_days=29, split_day=15)
    got = {tx["booking_date"]: p.label for p in result.periods for tx in p.transactions}
    assert got == {"30-12-2025": "01/2026", "10-02-2026": "02/2026", "01-03-2026": "03/2026",
                   "10-04-2026": "04/2026", "30-04-2026": "05/2026"}


def test_a_boundary_whose_label_disagrees_is_flagged(env):
    rows = dict(ROWS, **{"03/2026": ([(date(2026, 2, 10), 7.25, "Early")], [])})
    fill(env, {"03/2026": rows["03/2026"]})
    _, out, _ = run(env, answer="no")
    line = next(ln for ln in out.splitlines() if "-> 03/2026" in ln)
    assert "10-02-2026" in line and "!" in line


def test_two_sheets_with_the_same_boundary_are_refused(env):
    fill(env, {"04/2026": ([(date(2026, 2, 24), 1.0, "Same day")], [])})
    code, out, asked = run(env)
    assert code == 2 and asked == []
    assert not env.state_path.exists()


# ── the weak ledger ─────────────────────────────────────────────────────────

def test_the_weak_ledger_holds_date_amount_and_block_only(env):
    run(env)
    data = seeded(env)
    assert data["01/2026"] == {"2025-12-27|12.50|expenses": 1, "2025-12-24|314.10|income": 1}
    assert data["03/2026"] == {"2026-02-24|7.25|expenses": 2}      # a multiset
    text = env.ledger_path.read_text()
    assert SECRET not in text and "Etentje" not in text and "Boodschappen" not in text
    assert "06/2026" not in data


# ── confirmation, refusals, privacy ─────────────────────────────────────────

def test_nothing_is_written_without_yes(env):
    code, out, asked = run(env, answer="no")
    assert code == 1 and asked
    assert not env.state_path.exists() and not env.ledger_path.exists()


def test_an_open_run_refuses_before_reading(env):
    RunStore(str(env.runs_dir)).create("u1", files=[], force=False, upload_dir=None,
                                       anchor_before=None)
    code, out, asked = run(env)
    assert code == 2 and asked == [] and "u1" in out


def test_the_output_holds_no_amounts_or_descriptions(env):
    _, out, _ = run(env)
    for secret in (SECRET, "Etentje", "314.1", "1800", "Koffie"):
        assert secret not in out


# ── --set-anchor ────────────────────────────────────────────────────────────

def current(env):
    save_anchor(env.state_path, Anchor(*EXPECTED_ANCHOR, EXPECTED_HISTORY))


def test_set_anchor_forward_pushes_the_current_anchor_onto_history(env):
    current(env)
    code, _, _ = run(env, "--set-anchor", "24-05-2026", "06/2026")
    anchor = load_anchor(env.state_path)
    assert code == 0
    assert (anchor.boundary, anchor.label) == (date(2026, 5, 24), "06/2026")
    assert anchor.history == (EXPECTED_ANCHOR,) + EXPECTED_HISTORY


def test_set_anchor_back_drops_the_newer_boundaries(env):
    current(env)
    run(env, "--set-anchor", "23-03-2026", "04/2026")
    anchor = load_anchor(env.state_path)
    assert (anchor.boundary, anchor.label) == (date(2026, 3, 23), "04/2026")
    assert anchor.history == EXPECTED_HISTORY[1:]


def test_set_anchor_without_a_current_anchor_has_no_history(env):
    run(env, "--set-anchor", "24-05-2026", "06/2026")
    assert load_anchor(env.state_path).history == ()


def test_set_anchor_leaves_the_ledger_alone_and_asks_first(env):
    code, _, asked = run(env, "--set-anchor", "24-05-2026", "06/2026", answer="no")
    assert code == 1 and asked
    assert not env.state_path.exists() and not env.ledger_path.exists()


@pytest.mark.parametrize("args", [("31-02-2026", "06/2026"), ("24-05-2026", "6/26")])
def test_set_anchor_rejects_a_bad_date_or_label(env, args):
    code, _, asked = run(env, "--set-anchor", *args)
    assert code == 2 and asked == []


def test_parse_date_is_the_periods_one():
    assert seed_state.parse_date is parse_date


def test_a_hand_switched_negative_amount_seeds_its_absolute_value(env):
    fill(env, {"04/2026": ([(date(2026, 3, 23), -4.0, "Switched")], [])})
    run(env)
    assert seeded(env)["04/2026"] == {"2026-03-23|4.00|expenses": 1}


@pytest.mark.parametrize("answer", ["", "y", "YES please", "ja"])
def test_only_an_exact_yes_confirms(env, answer):
    code, _, _ = run(env, answer=answer)
    assert code == 1 and not env.state_path.exists()
