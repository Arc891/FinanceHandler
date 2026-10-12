"""
The fine-tuned Laya arm of the shadow-eval (jev-investigation.md §5.1 step 1,
arm 1), used by shadow_local.py: Laya multilingual (mmBERT-base with Laya's
decision head) fine-tuned with `laya.train.finetune` on the household's own
labels, one choice question per block (17 expense, 7 income categories, under
the head's ~20-option budget).

Tier 0: the training data is raw transaction text. It is written 0600 into a
0700 folder under --out-dir, removed as soon as a fit ends, and the
checkpoints are removed when their model is done. The run refuses to start
unless the process has no network: run it inside `unshare -rn`, with the
checkpoint downloaded beforehand.

    # once, with network: the base checkpoint
    venv-eval/bin/python -c "from huggingface_hub import snapshot_download as s; \\
        print(s('convaiinnovations/laya-multilingual', revision='e4e9ddf21a7b'))"
    # the run, without network
    HF_HUB_OFFLINE=1 unshare -rn venv-eval/bin/python scripts/shadow_local.py laya \\
        --base <printed path> --export ~/finance-eval/export.jsonl --out-dir ~/finance-eval
"""

import json
import math
import os
import shutil
import socket
import tempfile

import shadow_local as sl

REPO = "convaiinnovations/laya-multilingual"
REVISION = "e4e9ddf21a7b"
BATCH = 32
INSTRUCTIONS = "Which category of this Dutch household's monthly budget does this bank transaction belong to?"


class NotIsolated(Exception):
    """The process can reach the network; the Tier-0 run does not start."""


def network_isolated() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
    except OSError:
        return True
    return False


def question(options):
    return {"category": {"type": "choice", "instructions": INSTRUCTIONS,
                         "criteria": {o: o for o in options}}}


class LayaModel:
    def __init__(self, base, device, epochs, workdir, finetune=None, load=None, grad_accum=8):
        self.base, self.device, self.epochs, self.workdir = base, device, epochs, workdir
        self.grad_accum = grad_accum
        self._finetune, self._load = finetune, load
        self.dir = None

    def fit(self, rows):
        if self._finetune is None:
            from laya.train import finetune
            self._finetune = finetune
        if self._load is None:
            import laya
            self._load = laya.load
        from_blocks = {}
        for r in rows:
            from_blocks.setdefault(r["block"], set()).add(r["truth"])
        self.options = {b: sorted(v) for b, v in from_blocks.items()}
        self.dir = tempfile.mkdtemp(prefix="laya-", dir=self.workdir)       # 0700
        data = os.path.join(self.dir, "train.jsonl")
        fd = os.open(data, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"state": sl.row_text(r["tx"]),
                                    "questions": question(self.options[r["block"]]),
                                    "expected": {"category": r["truth"]}}, ensure_ascii=False) + "\n")
        try:
            from laya.train import TrainConfig
        except ImportError:                      # the fakes in the tests
            from types import SimpleNamespace as TrainConfig
        try:
            self._finetune(data, self.base, os.path.join(self.dir, "ckpt"),
                           config=TrainConfig(epochs=self.epochs, grad_accum=self.grad_accum, seed=0), device=self.device)
        finally:
            os.remove(data)
        self.agent = self._load(os.path.join(self.dir, "ckpt"), device=self.device)

    def logits(self, rows):
        classes = sorted({c for opts in self.options.values() for c in opts})
        out = [None] * len(rows)
        by_block = {}
        for i, r in enumerate(rows):
            by_block.setdefault(r["block"], []).append(i)
        for block, idx in by_block.items():
            opts = self.options.get(block, [])
            if not opts:
                for i in idx:
                    out[i] = [-math.inf] * len(classes)
                continue
            got = self.agent.predict_batch([sl.row_text(rows[i]["tx"]) for i in idx], question(opts),
                                           batch_size=BATCH)
            for i, res in zip(idx, got):
                probs = res["answers"]["category"].get("probabilities") or {}
                out[i] = [math.log(max(float(probs.get(c, 0.0)), 1e-6)) if c in opts else -math.inf
                          for c in classes]
        return classes, out

    def close(self):
        self.agent = None
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir = None


def factory(args):
    """make_model for shadow_local.run_arm; stops unless the network is cut."""
    if not network_isolated():
        raise NotIsolated("the network is reachable: run inside `unshare -rn` (see shadow_laya.py)")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    workdir = os.path.join(args.out_dir, "laya-work")
    os.makedirs(workdir, mode=0o700, exist_ok=True)
    settings = getattr(args, "settings", None)
    if not settings:
        return lambda: LayaModel(args.base, args.device, args.epochs, workdir)
    return {f"{e}x{a}": (lambda e=e, a=a: LayaModel(args.base, args.device, e, workdir, grad_accum=a))
            for e, a in sl.parse_settings(settings)}
