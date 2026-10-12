"""
Tests for scripts/shadow_laya.py, the fine-tuned Laya arm of the shadow-eval
(jev-investigation.md §5.1 step 1, arm 1). Laya's finetune and load are
fakes here; the real model runs on the workstation GPU only. Synthetic data.
"""

import json
import math
import os
import stat

import pytest

import shadow_laya as sla
import shadow_local as sl
from test_shadow_local import export_rows

SECRET = "Jolanda Vermeulen"


class FakeAgent:
    def __init__(self, options):
        self.calls = []
        self.options = options

    def predict_batch(self, states, questions, batch_size=None):
        self.calls.append((list(states), questions))
        opts = list(questions["category"]["criteria"])
        return [{"answers": {"category": {"choice": opts[0], "probabilities":
                                          {o: (0.9 if i == 0 else 0.1 / max(len(opts) - 1, 1))
                                           for i, o in enumerate(opts)}}}} for _ in states]


def make(tmp_path, seen):
    def finetune(data, model_dir, output_dir, config=None, device=None):
        assert stat.S_IMODE(os.stat(data).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(os.path.dirname(data)).st_mode) == 0o700
        with open(data) as f:
            seen.extend(json.loads(line) for line in f)
        os.makedirs(output_dir)
        seen.append({"config": config, "base": model_dir, "device": device})

    return sla.LayaModel(base="/models/laya", device="cuda", epochs=2, workdir=str(tmp_path),
                         finetune=finetune, load=lambda path, device=None: FakeAgent(None))


def test_training_rows_hold_the_text_the_blocks_options_and_the_label(tmp_path):
    seen = []
    rows = export_rows()
    rows[0]["tx"]["counterparty"] = SECRET
    model = make(tmp_path, seen)
    model.fit(rows)
    data = [s for s in seen if "state" in s]
    assert len(data) == len(rows)
    first = data[0]
    assert SECRET in first["state"]
    assert first["expected"] == {"category": rows[0]["truth"]}
    opts = set(first["questions"]["category"]["criteria"])
    assert opts == {"Boodschappen", "Abonnementen", "Energie"}
    income = next(d for d, r in zip(data, rows) if r["block"] == "income")
    assert set(income["questions"]["category"]["criteria"]) == {"Salaris"}
    cfg = seen[-1]
    assert cfg["config"].epochs == 2 and cfg["base"] == "/models/laya" and cfg["device"] == "cuda"


def test_the_training_file_is_gone_after_the_fit_and_the_checkpoint_after_close(tmp_path):
    model = make(tmp_path, [])
    model.fit(export_rows())
    leftovers = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs]
    assert not any(f.endswith(".jsonl") for f in leftovers)
    model.close()
    assert os.listdir(tmp_path) == []


def test_logits_are_log_probabilities_inside_the_block_only(tmp_path):
    model = make(tmp_path, [])
    rows = export_rows()
    model.fit(rows)
    want = [rows[0], rows[3]]                      # an expense and an income row
    classes, logits = model.logits(want)
    assert classes == sorted({"Boodschappen", "Abonnementen", "Energie", "Salaris"})
    exp = dict(zip(classes, logits[0]))
    assert exp["Salaris"] == -math.inf
    assert exp["Abonnementen"] == pytest.approx(math.log(0.9))   # first option offered
    inc = dict(zip(classes, logits[1]))
    assert inc["Salaris"] == pytest.approx(math.log(0.9))
    assert inc["Boodschappen"] == -math.inf


def test_logits_of_no_rows(tmp_path):
    model = make(tmp_path, [])
    model.fit(export_rows())
    classes, logits = model.logits([])
    assert logits == []


def test_the_arm_refuses_to_start_with_the_network_reachable(monkeypatch):
    monkeypatch.setattr(sla, "network_isolated", lambda: False)
    with pytest.raises(sla.NotIsolated):
        sla.factory(type("A", (), {"base": "/x", "device": "cuda", "epochs": 1, "out_dir": "/tmp"})())


def test_run_arm_closes_every_model(tmp_path):
    closed = []
    from test_shadow_local import MemoModel

    class M(MemoModel):
        def close(self):
            closed.append(1)

    sl.run_arm(export_rows(), M, "alternating")
    assert len(closed) == sl.FOLDS + 1


def test_the_setting_reaches_the_training_config(tmp_path):
    seen = []
    model = make(tmp_path, seen)
    model.grad_accum = 1
    model.fit(export_rows())
    assert seen[-1]["config"].grad_accum == 1


# ── fail closed (review 2026-10-12) ─────────────────────────────────────────

def _no_route(*a, **k):
    raise OSError("unreachable")


def test_isolated_means_loopback_only_and_no_route(monkeypatch):
    monkeypatch.setattr(sla.socket, "if_nameindex", lambda: [(1, "lo")])
    monkeypatch.setattr(sla.socket, "create_connection", _no_route)
    assert sla.network_isolated()


def test_another_interface_is_not_isolated_even_when_one_address_is_blocked(monkeypatch):
    monkeypatch.setattr(sla.socket, "if_nameindex", lambda: [(1, "lo"), (2, "eth0")])
    monkeypatch.setattr(sla.socket, "create_connection", _no_route)
    assert not sla.network_isolated()


def test_a_reachable_address_is_not_isolated(monkeypatch):
    class Conn:
        def close(self):
            pass
    monkeypatch.setattr(sla.socket, "if_nameindex", lambda: [(1, "lo")])
    monkeypatch.setattr(sla.socket, "create_connection", lambda *a, **k: Conn())
    assert not sla.network_isolated()


def test_a_failed_write_leaves_no_training_file(tmp_path):
    model = make(tmp_path, [])
    rows = export_rows()
    rows[-1]["truth"] = {"not", "json"}                # json.dumps fails on the last line
    with pytest.raises(TypeError):
        model.fit(rows)
    model.close()
    assert os.listdir(tmp_path) == []


def test_a_failed_fit_leaves_no_training_file(tmp_path):
    def finetune(data, model_dir, output_dir, config=None, device=None):
        os.makedirs(output_dir)
        raise RuntimeError("out of memory")
    model = sla.LayaModel(base="/m", device="cuda", epochs=1, workdir=str(tmp_path), finetune=finetune,
                          load=lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        model.fit(export_rows())
    files = [f for _, _, fs in os.walk(tmp_path) for f in fs]
    assert not any(f.endswith(".jsonl") for f in files)
    model.close()
    assert os.listdir(tmp_path) == []
