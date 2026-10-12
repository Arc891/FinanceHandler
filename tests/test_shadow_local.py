"""
Tests for scripts/shadow_local.py, the workstation arms of the shadow-eval
(jev-investigation.md §5.1 step 1, arms 1 and 4).

The plumbing is tested with a fake model: features, month folds, temperature
scaling, the block mask, out-of-fold answers on the train months, no test
month ever reaching a fit, and the files. The real classical model runs only
where scikit-learn is installed. All data is synthetic.
"""

import math
import os
import stat

import pytest

import shadow_eval as se
import shadow_local as sl

MONTHS = [f"{m:02d}/2024" for m in range(6, 13)] + [f"{m:02d}/2025" for m in range(1, 13)]
SECRET = "Jolanda Vermeulen"


def tx(counterparty="Jumbo", remittance="pas 012", direction="out", amount=12.5,
       code="BEA", weekday=2, hour=None, iban="", role=None, pot_hint=False):
    return {"direction": direction, "amount": amount, "code": code, "weekday": weekday,
            "hour": hour, "counterparty": counterparty, "remittance": remittance,
            "counterparty_iban": iban, "account_role": role, "pot_hint": pot_hint}


def export_rows(per_month=4):
    """Every month: two shops (routed), one rule row, one income row (routed)."""
    rows, i = [], 0
    for label in MONTHS:
        for cp, truth, routed, block in (("Jumbo", "Boodschappen", True, "expenses"),
                                         ("Netflix", "Abonnementen", True, "expenses"),
                                         ("Eneco", "Energie", False, "expenses"),
                                         ("Werk", "Salaris", True, "income"))[:per_month]:
            direction = "in" if block == "income" else "out"
            rows.append({"id": i, "label": label, "block": block, "group": i, "truth": truth,
                         "routed": routed, "tx": tx(counterparty=cp, direction=direction)})
            i += 1
    return rows


# ── features and text ───────────────────────────────────────────────────────

def test_features_cover_code_amount_role_weekday_and_words():
    f = sl.features(tx(counterparty="Albert Heijn 1234", remittance="Betaalautomaat pas 012",
                       role="savings", hour=14, pot_hint=True, iban="NL11ASNB0000000001"))
    assert f["direction=out"] == 1 and f["code=BEA"] == 1 and f["role=savings"] == 1
    assert f["weekday=2"] == 1 and f["hour=14"] == 1 and f["pot_hint"] == 1
    assert f["cp:albert"] == 1 and f["cp:heijn"] == 1 and f["rem:betaalautomaat"] == 1
    assert f["iban=NL11ASNB0000000001"] == 1
    assert f["log_amount"] == pytest.approx(math.log1p(12.5))


def test_features_of_a_row_without_role_or_hour():
    f = sl.features(tx(role=None, hour=None))
    assert f["role=none"] == 1 and f["hour=none"] == 1


def test_text_holds_the_row_for_the_local_encoder():
    text = sl.row_text(tx(counterparty=SECRET, remittance="etentje", direction="in", amount=40.0,
                          role="partner_personal", pot_hint=True))
    assert SECRET in text and "etentje" in text and "40.00" in text
    assert "partner_personal" in text and "in" in text


# ── folds, temperature, mask ────────────────────────────────────────────────

def test_month_folds_are_chronological_round_robin():
    folds = sl.month_folds(MONTHS[:10], 5)
    assert folds["06/2024"] == 0 and folds["07/2024"] == 1 and folds["11/2024"] == 0
    assert sorted(set(folds.values())) == [0, 1, 2, 3, 4]


def test_fewer_months_than_folds_gives_one_fold_per_month():
    folds = sl.month_folds(["06/2024", "07/2024"], 5)
    assert sorted(folds.values()) == [0, 1]


def test_softmax_with_temperature():
    p = sl.softmax([2.0, 0.0], 1.0)
    assert p[0] == pytest.approx(1 / (1 + math.exp(-2)))
    assert sl.softmax([2.0, 0.0], 1e9)[0] == pytest.approx(0.5, abs=1e-6)
    assert sl.softmax([2.0, -math.inf], 1.0) == [1.0, 0.0]


def test_an_overconfident_model_gets_a_temperature_above_one():
    logits = [[5.0, 0.0]] * 6 + [[0.0, 5.0]] * 4     # argmax right 6 of 10, at 99%
    gold = [0] * 10
    assert sl.fit_temperature(logits, gold) > 1.5


def test_an_underconfident_model_gets_a_temperature_below_one():
    logits = [[0.2, 0.0]] * 10
    assert sl.fit_temperature(logits, [0] * 10) < 1.0


def test_no_calibration_rows_leave_the_temperature_at_one():
    assert sl.fit_temperature([], []) == 1.0


def test_the_mask_keeps_only_the_blocks_classes():
    classes = ["Boodschappen", "Salaris"]
    out = sl.masked([3.0, 5.0], classes, {"Boodschappen"})
    assert out[0] == 3.0 and out[1] == -math.inf


# ── the arm run, with a fake model ──────────────────────────────────────────

class MemoModel:
    """Remembers counterparty -> category from what it was fitted on."""
    fits = []

    def fit(self, rows):
        MemoModel.fits.append([r["id"] for r in rows])
        self.seen = {r["tx"]["counterparty"]: r["truth"] for r in rows}
        self.classes = sorted({r["truth"] for r in rows})

    def logits(self, rows):
        out = []
        for r in rows:
            cat = self.seen.get(r["tx"]["counterparty"])
            out.append([4.0 if c == cat else 0.0 for c in self.classes])
        return self.classes, out


@pytest.fixture(autouse=True)
def reset_fits():
    MemoModel.fits = []


def test_no_fit_ever_sees_a_test_month():
    rows = export_rows()
    sl.run_arm(rows, MemoModel, "alternating")
    split = se.split_months([r["label"] for r in rows], "alternating")
    by_id = {r["id"]: r for r in rows}
    for fitted in MemoModel.fits:
        assert all(split[by_id[i]["label"]] == "train" for i in fitted)
    assert len(MemoModel.fits) == sl.FOLDS + 1


def test_train_month_answers_are_out_of_fold():
    rows = export_rows()
    # a counterparty seen in one train month only: its own fold never saw it
    lone = next(r for r in rows if r["label"] == "06/2024" and r["tx"]["counterparty"] == "Jumbo")
    lone["tx"] = tx(counterparty="Eenmalig")
    preds, _ = sl.run_arm(rows, MemoModel, "alternating")
    assert preds[lone["id"]]["confidence"] < 0.6


def test_answers_cover_routed_rows_of_every_month_only():
    rows = export_rows()
    preds, _ = sl.run_arm(rows, MemoModel, "forward")
    routed = {r["id"] for r in rows if r["routed"]}
    assert set(preds) == routed


def test_an_answer_stays_inside_its_block():
    rows = export_rows()
    preds, _ = sl.run_arm(rows, MemoModel, "alternating")
    for r in rows:
        if r["routed"] and r["block"] == "income":
            assert preds[r["id"]]["category"] == "Salaris"
        elif r["routed"]:
            assert preds[r["id"]]["category"] != "Salaris"


def test_a_well_known_counterparty_is_answered_confidently_in_a_test_month():
    rows = export_rows()
    preds, info = sl.run_arm(rows, MemoModel, "alternating")
    test_jumbo = next(r for r in rows if r["label"] == "07/2024" and r["tx"]["counterparty"] == "Jumbo")
    assert preds[test_jumbo["id"]]["category"] == "Boodschappen"
    assert preds[test_jumbo["id"]]["confidence"] > 0.5
    assert info["temperature"] > 0


# ── files and the printed lines ─────────────────────────────────────────────

def test_main_writes_one_private_file_per_split_and_prints_counts_only(tmp_path, capsys, monkeypatch):
    rows = export_rows()
    rows[0]["tx"]["counterparty"] = SECRET
    export = tmp_path / "export.jsonl"
    se.write_private_jsonl(str(export), {"kind": "export", "fingerprint": "f" * 16}, rows)
    monkeypatch.setitem(sl.ARMS, "memo", lambda args: MemoModel)
    code = sl.main(["memo", "--export", str(export), "--out-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    for split in se.SPLITS:
        path = tmp_path / f"pred-memo-{split}.jsonl"
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        header, body = se.read_jsonl(str(path))
        assert header == {"kind": "predictions", "arm": "memo", "split": split, "local": True,
                          "fingerprint": "f" * 16, "temperature": header["temperature"]}
        assert {p["id"] for p in body} == {r["id"] for r in rows if r["routed"]}
    assert SECRET not in out and "Jumbo" not in out


def test_main_refuses_a_file_that_is_not_an_export(tmp_path, capsys):
    path = tmp_path / "rows.jsonl"
    se.write_private_jsonl(str(path), {"kind": "rows", "fingerprint": "f" * 16}, [])
    assert sl.main(["classical", "--export", str(path), "--out-dir", str(tmp_path)]) == 2


# ── the real classical model ────────────────────────────────────────────────

def test_the_classical_model_learns_counterparties():
    pytest.importorskip("sklearn")
    rows = export_rows()
    preds, _ = sl.run_arm(rows, sl.ClassicalModel, "alternating")
    test_rows = [r for r in rows if r["label"] == "07/2024" and r["routed"]]
    assert all(preds[r["id"]]["category"] == r["truth"] for r in test_rows)
