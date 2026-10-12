"""
Tests for the shadow-eval outputs of scripts/eval_categoriser.py
(jev-investigation.md §5.1 step 1): the rows file, Sonnet's predictions and
the private export the local arms train on.

The rows and predictions files hold no transaction content; the export does
and is written 0600 and never printed. All data is synthetic.
"""

import asyncio
import os
import stat
from types import SimpleNamespace

import eval_categoriser as ev
import shadow_eval as se
from fakes import expense_tx, income_tx
from test_eval_categoriser import (SECRET_NAME, SECRET_REM, VALID, FakeGc, raw,
                                   root_logger, sheet_row)  # noqa: F401

SAVINGS = "NL11ASNB0000000001"


def res(category, method="ai_auto", confidence=0.9):
    return SimpleNamespace(category=category, method=method, confidence=confidence)


def matched():
    """Four rows in 03/2024: two share a key (same day, amount, block)."""
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-5.00", name=SECRET_NAME, rem=SECRET_REM, seq="1")),
           raw(expense_tx(date_str="17-03-2024", amount="-5.00", name="Jumbo", rem="pas 1", seq="2")),
           raw(expense_tx(date_str="18-03-2024", amount="-9.99", name="Netflix", rem="abo", seq="3")),
           raw(income_tx(date_str="19-03-2024", amount="100.00", name="Werk", rem="loon", seq="4"))]
    rows = [sheet_row(date="2024-03-17", amount="5.00", category="Boodschappen"),
            sheet_row(date="2024-03-17", amount="5.00", category="Dates/uitjes"),
            sheet_row(date="2024-03-18", amount="9.99", category="Abonnementen"),
            sheet_row(block="income", date="2024-03-19", amount="100.00", category="Salaris")]
    return ev.match_rows(txs, rows, VALID, {})


def test_rows_carry_month_block_group_truth_and_routing_only():
    m = matched()
    results = [res("Boodschappen"), res("Boodschappen"), res("Abonnementen", "regex", 1.0),
               res(None, "none", 0.0)]
    fp, rows = ev.rows_payload(m, results)
    assert [r["id"] for r in rows] == [0, 1, 2, 3]
    assert [r["routed"] for r in rows] == [True, True, False, True]
    assert rows[0]["group"] == rows[1]["group"] != rows[2]["group"]
    assert sorted([rows[0]["truth"], rows[1]["truth"]]) == ["Boodschappen", "Dates/uitjes"]
    assert rows[3]["block"] == "income" and rows[3]["label"] == "03/2024"
    assert set(rows[0]) == {"id", "label", "block", "group", "truth", "routed"}
    text = repr(rows) + fp
    for secret in (SECRET_NAME, SECRET_REM, "5.00", "17-03", "2024-03-17"):
        assert secret not in text


def test_the_fingerprint_is_the_same_for_the_same_matching():
    fp1, _ = ev.rows_payload(matched(), [res("x")] * 4)
    fp2, _ = ev.rows_payload(matched(), [res(None, "none", 0.0)] * 4)
    assert fp1 == fp2


def test_predictions_cover_routed_rows_only():
    m = matched()
    results = [res("Boodschappen", "ai_auto", 0.9), res("Dates/uitjes", "ai_manual_needed", 0.3),
               res("Abonnementen", "regex", 1.0), res(None, "none", 0.0)]
    preds = ev.predictions_payload(m, results)
    assert preds == [{"id": 0, "category": "Boodschappen", "confidence": 0.9},
                     {"id": 1, "category": "Dates/uitjes", "confidence": 0.3},
                     {"id": 3, "category": None, "confidence": 0.0}]


def test_the_export_holds_what_the_local_arms_train_on():
    m = matched()
    results = [res(None, "none", 0.0)] * 2 + [res("Abonnementen", "regex", 1.0), res(None, "none", 0.0)]
    _, rows = ev.export_payload(m, results, roles={"savings": [SAVINGS]})
    assert len(rows) == 4
    tx = rows[0]["tx"]
    assert tx["direction"] == "out" and tx["amount"] == 5.0
    assert tx["counterparty"] == SECRET_NAME and tx["remittance"] == SECRET_REM
    assert tx["weekday"] == 6            # 17-03-2024 was a Sunday
    assert set(tx) >= {"code", "hour", "counterparty_iban", "account_role", "pot_hint"}
    assert rows[2]["routed"] is False and rows[2]["truth"] == "Abonnementen"


def test_the_export_marks_a_purchase_one_savings_transfer_explains():
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-80.00", name="Winkel", seq="1")),
           {**raw(income_tx(date_str="16-03-2024", amount="80.00", name="Spaar", seq="2")),
            "counterparty_iban": SAVINGS}]
    rows = [sheet_row(date="2024-03-17", amount="80.00", category="Boodschappen"),
            sheet_row(block="income", date="2024-03-16", amount="80.00", category="Salaris")]
    m = ev.match_rows(txs, rows, VALID, {})
    results = [res(None, "none", 0.0), res("Salaris", "regex", 1.0)]
    _, out = ev.export_payload(m, results, roles={"savings": [SAVINGS]})
    assert out[0]["tx"]["pot_hint"] is True
    assert out[1]["tx"]["account_role"] == "savings"


class RulesOnlyEngine:
    """Regex decides the income row; the rest is left to the AI."""

    def __init__(self):
        self.ai_enabled = False

    async def batch_categorize(self, txs, **kwargs):
        return [res("Salaris", "regex", 1.0) if tx["credit_debit_indicator"] == "CRDT"
                else res(None, "none", 0.0) for tx in txs]


def books():
    return {"03/2024": {
        "B1:E": [["Date"], [], [], [45368, 47.35, SECRET_REM, "Boodschappen"]],
        "G1:J": [["Date"], [], [], [45369, 1234.56, SECRET_NAME, "Salaris"]]}}


def setup_run(monkeypatch):
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-47.35", name=SECRET_NAME, rem=SECRET_REM, seq="1")),
           raw(income_tx(date_str="18-03-2024", amount="1234.56", name=SECRET_NAME, rem=SECRET_REM, seq="2"))]
    monkeypatch.setattr(ev, "load_exports", lambda paths: (txs, 0))
    monkeypatch.setattr(ev, "service_account_client", lambda p: FakeGc(books()))
    monkeypatch.setattr(ev, "MIN_INTERVAL", 0.0)


def test_export_end_to_end_writes_private_files_and_prints_no_content(
        monkeypatch, capsys, tmp_path, root_logger):
    setup_run(monkeypatch)
    monkeypatch.setattr(ev, "rules_engine", lambda local_rules: RulesOnlyEngine())
    export, rows = tmp_path / "export.jsonl", tmp_path / "rows.jsonl"
    code = ev.main(["--export-out", str(export), "--rows-out", str(rows), "x.csv"])
    out = capsys.readouterr().out
    assert code == 0
    for p in (export, rows):
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    eh, erows = se.read_jsonl(str(export))
    rh, rrows = se.read_jsonl(str(rows))
    assert eh["kind"] == "export" and rh["kind"] == "rows"
    assert eh["fingerprint"] == rh["fingerprint"]
    assert [r["routed"] for r in rrows] == [True, False]
    assert erows[0]["tx"]["counterparty"] == SECRET_NAME
    assert SECRET_NAME not in rows.read_text()
    assert "not shown" in out
    for secret in (SECRET_NAME, SECRET_REM, "47.35", "1234.56"):
        assert secret not in out


class SonnetEngine:
    async def batch_categorize(self, txs, **kwargs):
        return [res("Salaris", "regex", 1.0) if tx["credit_debit_indicator"] == "CRDT"
                else res("Boodschappen", "ai_auto", 0.9) for tx in txs]


def test_an_ai_run_writes_rows_and_predictions_with_one_fingerprint(
        monkeypatch, capsys, tmp_path, root_logger):
    setup_run(monkeypatch)
    monkeypatch.setattr(ev, "build_engine", lambda model, local_rules, make_ai=None: SonnetEngine())
    rows, preds = tmp_path / "rows.jsonl", tmp_path / "pred-sonnet.jsonl"
    code = ev.main(["--rows-out", str(rows), "--predictions-out", str(preds), "x.csv"])
    capsys.readouterr()
    assert code == 0
    rh, rrows = se.read_jsonl(str(rows))
    ph, prows = se.read_jsonl(str(preds))
    assert ph == {"kind": "predictions", "arm": "sonnet", "split": "any", "local": False,
                  "fingerprint": rh["fingerprint"]}
    assert prows == [{"id": 0, "category": "Boodschappen", "confidence": 0.9}]
    assert stat.S_IMODE(os.stat(preds).st_mode) == 0o600


def test_predictions_out_needs_an_ai_run(capsys):
    import pytest
    with pytest.raises(SystemExit):
        ev.main(["--predictions-out", "p.jsonl", "--dry-run", "x.csv"])
    with pytest.raises(SystemExit):
        ev.main(["--predictions-out", "p.jsonl", "--export-out", "e.jsonl", "x.csv"])
    with pytest.raises(SystemExit):
        ev.main(["--export-out", "e.jsonl", "--rules", "x.csv"])
