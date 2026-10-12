"""
Tests for scripts/jev_client.py and the Jev arm of eval_categoriser.py
(jev-investigation.md §5.1 step 1, arm 2: hosted Jev through OpenRouter,
zero data retention enforced, the anonymised input Sonnet gets).

No network: the HTTP session is a fake. All data is synthetic.
"""

import json
import os
import stat
from types import SimpleNamespace

import pytest

import eval_categoriser as ev
import jev_client as jc
import shadow_eval as se
from fakes import expense_tx, income_tx
from test_eval_categoriser import (SECRET_NAME, SECRET_REM, VALID, FakeGc, raw,  # noqa: F401
                                   root_logger, sheet_row)

KEY = "sk-or-test-not-a-real-key"
EXPENSES = {"Boodschappen": "", "Abonnementen": "", "Dates/uitjes": ""}
INCOME = {"Salaris": "", "Gift": ""}


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}

    def json(self):
        return self._body


def answer(choice="Boodschappen", probs=None, model="typesafe/jev-1.13-20260917", provider="TypeSafe"):
    probs = probs or {"Boodschappen": 0.8, "Abonnementen": 0.15, "other": 0.05}
    return {"id": "gen-dec-1", "model": model, "provider": provider,
            "answers": {"category": {"type": "choice", "choice": choice, "confidence": 0.7,
                                     "probabilities": probs},
                        "transfer": {"type": "noul", "noul": 0.1},
                        "refund": {"type": "noul", "noul": 0.02},
                        "recurring": {"type": "noul", "noul": 0.6}},
            "usage": {"input_tokens": 400, "output_tokens": 0, "cost": 0.00002}}


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts, self.gets = [], []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append(SimpleNamespace(url=url, json=json, headers=headers, timeout=timeout))
        return self.responses.pop(0)

    def get(self, url, timeout=None):
        self.gets.append(url)
        return self.responses.pop(0)


# ── questions ───────────────────────────────────────────────────────────────

def test_the_category_question_offers_the_blocks_categories_and_other():
    q = jc.questions(EXPENSES)
    cat = q["category"]
    assert cat["type"] == "choice"
    assert set(cat["criteria"]) == set(EXPENSES) | {"other"}
    assert {"transfer", "refund", "recurring"} <= set(q)
    assert all(q[k]["type"] == "noul" for k in ("transfer", "refund", "recurring"))


def test_category_descriptions_come_from_the_example_rules_sonnet_sees():
    desc = jc.category_descriptions(["Boodschappen", "Abonnementen"],
                                    {r"(?i)\bALBERT HEIJN\b": ("{c}", "Boodschappen"),
                                     r"JUMBO|LIDL": ("x", "Boodschappen")})
    assert "ALBERT HEIJN" in desc["Boodschappen"] and "JUMBO" in desc["Boodschappen"]
    assert "\\b" not in desc["Boodschappen"] and "(?i)" not in desc["Boodschappen"]
    assert desc["Abonnementen"] == "Abonnementen"


# ── one decision ────────────────────────────────────────────────────────────

def test_a_decision_is_pinned_zdr_only_and_typesafe_only():
    s = Session([Resp(body=answer())])
    jc.decide(s, KEY, {"transaction": {}}, jc.questions(EXPENSES))
    post = s.posts[0]
    assert post.url == "https://openrouter.ai/api/v1/systemone"
    assert post.headers["Authorization"] == f"Bearer {KEY}"
    assert post.json["model"] == "typesafe/jev-1.13"
    assert post.json["provider"] == {"zdr": True, "only": ["typesafe"], "allow_fallbacks": False,
                                     "data_collection": "deny"}


def test_the_confidence_is_the_top_probability_not_jevs_peakedness():
    got = jc.decide(Session([Resp(body=answer())]), KEY, {}, jc.questions(EXPENSES))
    assert got["category"] == "Boodschappen" and got["confidence"] == 0.8
    assert got["nouls"] == {"transfer": 0.1, "refund": 0.02, "recurring": 0.6}


def test_other_is_no_answer():
    got = jc.decide(Session([Resp(body=answer(choice="other", probs={"other": 0.9, "Boodschappen": 0.1}))]),
                    KEY, {}, jc.questions(EXPENSES))
    assert got["category"] is None and got["confidence"] == 0.9


def test_a_changed_model_stops_the_run():
    s = Session([Resp(body=answer(model="typesafe/jev-1.14-20261101"))])
    with pytest.raises(jc.ModelChanged):
        jc.decide(s, KEY, {}, jc.questions(EXPENSES))


def test_another_provider_stops_the_run():
    with pytest.raises(jc.JevError):
        jc.decide(Session([Resp(body=answer(provider="Other"))]), KEY, {}, jc.questions(EXPENSES))


def test_a_rate_limit_waits_as_told_and_retries():
    waits = []
    s = Session([Resp(429, headers={"Retry-After": "3"}), Resp(body=answer())])
    got = jc.decide(s, KEY, {}, jc.questions(EXPENSES), sleep=waits.append)
    assert got["category"] == "Boodschappen" and waits == [3.0]


def test_a_client_error_names_its_status_only():
    s = Session([Resp(400, body={"error": {"message": f"bad state {SECRET_NAME}"}})])
    with pytest.raises(jc.JevError) as exc:
        jc.decide(s, KEY, {}, jc.questions(EXPENSES), sleep=lambda _: None)
    assert "400" in str(exc.value) and SECRET_NAME not in str(exc.value)


def test_persistent_server_errors_give_up():
    s = Session([Resp(503)] * 5)
    with pytest.raises(jc.JevError):
        jc.decide(s, KEY, {}, jc.questions(EXPENSES), sleep=lambda _: None)


# ── zero data retention ─────────────────────────────────────────────────────

def zdr_list(*entries):
    return Resp(body={"data": list(entries)})


def test_zdr_is_confirmed_from_openrouters_public_list():
    s = Session([zdr_list({"model_id": "typesafe/jev-1.13", "provider_name": "TypeSafe"})])
    assert jc.zdr_ok(s) is True
    assert s.gets == ["https://openrouter.ai/api/v1/endpoints/zdr"]


def test_zdr_missing_for_jev_or_for_typesafe_is_refused():
    assert jc.zdr_ok(Session([zdr_list({"model_id": "other/model", "provider_name": "TypeSafe"})])) is False
    assert jc.zdr_ok(Session([zdr_list({"model_id": "typesafe/jev-1.13", "provider_name": "X"})])) is False
    assert jc.zdr_ok(Session([Resp(500)])) is False


# ── the arm inside the eval ─────────────────────────────────────────────────

def res(category, method="ai_auto", confidence=0.9):
    return SimpleNamespace(category=category, method=method, confidence=confidence)


def month():
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-5.00", name=SECRET_NAME, rem=SECRET_REM, seq="1")),
           raw(expense_tx(date_str="18-03-2024", amount="-9.99", name=SECRET_NAME, rem="abo", seq="2")),
           raw(income_tx(date_str="19-03-2024", amount="100.00", name="Werk", rem="loon", seq="3"))]
    rows = [sheet_row(date="2024-03-17", amount="5.00", category="Dates/uitjes"),
            sheet_row(date="2024-03-18", amount="9.99", category="Abonnementen"),
            sheet_row(block="income", date="2024-03-19", amount="100.00", category="Salaris")]
    return ev.match_rows(txs, rows, VALID, {})


def test_only_routed_rows_are_asked_with_anonymised_state_and_their_blocks_options():
    m = month()
    results = [res(None, "none", 0.0), res("Abonnementen", "regex", 1.0), res(None, "none", 0.0)]
    asked = []

    def ask(state, questions):
        asked.append((state, questions))
        return {"category": "Gift" if "Gift" in questions["category"]["criteria"] else "Boodschappen",
                "confidence": 0.7, "nouls": {}, "model": "typesafe/jev-1.13-20260917"}

    preds, model = ev.jev_payload(m, results, ask, EXPENSES, INCOME)
    assert [p["id"] for p in preds] == [0, 2]
    assert preds[0]["category"] == "Boodschappen" and preds[1]["category"] == "Gift"
    assert model == "typesafe/jev-1.13-20260917"
    sent = json.dumps([s for s, _ in asked])
    assert SECRET_NAME not in sent
    # the rule-decided row of the same counterparty is context, as Sonnet sees it
    ctx = asked[0][0]["same_counterparty_this_month"]
    assert [c["category"] for c in ctx] == ["Abonnementen"]
    assert set(asked[1][1]["category"]["criteria"]) == set(INCOME) | {"other"}


def test_jev_end_to_end_checks_zdr_reads_the_key_and_prints_no_content(
        monkeypatch, capsys, tmp_path, root_logger):
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-47.35", name=SECRET_NAME, rem=SECRET_REM, seq="1"))]
    books = {"03/2024": {"B1:E": [["Date"], [], [], [45368, 47.35, SECRET_REM, "Boodschappen"]],
                         "G1:J": []}}
    monkeypatch.setattr(ev, "load_exports", lambda paths: (txs, 0))
    monkeypatch.setattr(ev, "service_account_client", lambda p: FakeGc(books))
    monkeypatch.setattr(ev, "MIN_INTERVAL", 0.0)

    class Engine:
        async def batch_categorize(self, txs, **kw):
            return [res(None, "none", 0.0) for _ in txs]
    monkeypatch.setattr(ev, "rules_engine", lambda local_rules: Engine())
    session = Session([zdr_list({"model_id": "typesafe/jev-1.13", "provider_name": "TypeSafe"}),
                       Resp(body=answer())])
    monkeypatch.setattr(jc, "new_session", lambda: session)
    key = tmp_path / "openrouter.key"
    key.write_text(KEY + "\n")
    out_path = tmp_path / "pred-jev.jsonl"
    code = ev.main(["--jev-out", str(out_path), "--openrouter-key-file", str(key), "x.csv"])
    out = capsys.readouterr().out
    assert code == 0
    assert stat.S_IMODE(os.stat(out_path).st_mode) == 0o600
    header, body = se.read_jsonl(str(out_path))
    assert header["arm"] == "jev" and header["local"] is False and header["split"] == "any"
    assert header["model"] == "typesafe/jev-1.13-20260917"
    assert body == [{"id": 0, "category": "Boodschappen", "confidence": 0.8,
                     "nouls": {"transfer": 0.1, "refund": 0.02, "recurring": 0.6}}]
    for secret in (KEY, SECRET_NAME, SECRET_REM, "47.35"):
        assert secret not in out


def test_jev_refuses_to_run_without_zdr(monkeypatch, capsys, tmp_path, root_logger):
    txs = [raw(expense_tx(date_str="17-03-2024", amount="-47.35", seq="1"))]
    books = {"03/2024": {"B1:E": [["Date"], [], [], [45368, 47.35, "x", "Boodschappen"]], "G1:J": []}}
    monkeypatch.setattr(ev, "load_exports", lambda paths: (txs, 0))
    monkeypatch.setattr(ev, "service_account_client", lambda p: FakeGc(books))
    monkeypatch.setattr(ev, "MIN_INTERVAL", 0.0)
    session = Session([zdr_list()])
    monkeypatch.setattr(jc, "new_session", lambda: session)
    key = tmp_path / "k"
    key.write_text(KEY)
    code = ev.main(["--jev-out", str(tmp_path / "p.jsonl"), "--openrouter-key-file", str(key), "x.csv"])
    assert code == 2 and "zero data retention" in capsys.readouterr().out
    assert session.posts == []
    assert not (tmp_path / "p.jsonl").exists()


def test_a_changed_resolved_version_mid_run_stops_the_run():
    import jev_client
    m = month()
    results = [res(None, "none", 0.0), res("Abonnementen", "regex", 1.0), res(None, "none", 0.0)]
    versions = iter(["typesafe/jev-1.13-20260917", "typesafe/jev-1.13-20261001"])

    def ask(state, questions):
        return {"category": None, "confidence": 0.5, "nouls": {}, "model": next(versions)}

    with pytest.raises(jev_client.ModelChanged):
        ev.jev_payload(m, results, ask, EXPENSES, INCOME)
