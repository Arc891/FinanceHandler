#!/usr/bin/env python3
"""
The local arms of the shadow-eval (jev-investigation.md §5.1 step 1): trained
on the household's own labels, run on the workstation only.

    classical  logistic regression over the row's features (code, amount,
               account role, weekday, hour, words, counterparty account)
    laya       Laya multilingual fine-tuned on the row's text (GPU)

Input is the private export from `eval_categoriser.py --export-out` (0600,
holds transaction text; never printed, never pushed). Per split, the model
is fitted on every scored row of the train months, rules-decided ones
included. The train months get out-of-fold answers (month folds), which fit
the temperature and, in shadow_eval.py, the threshold; the routed rows of
the test months get the answers of a model fitted on all train months. An
answer is restricted to the categories its block (expenses or income) had in
training. Output: pred-<arm>-<split>.jsonl per split, 0600, ids and answers
only. The printed lines are counts.

    venv-eval/bin/python scripts/shadow_local.py classical \\
        --export ~/finance-eval/export.jsonl --out-dir ~/finance-eval
"""

import argparse
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shadow_eval as se  # noqa: E402

FOLDS = 5
WORD = re.compile(r"[a-z]{3,}")
WEEKDAYS = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")


# ── what a model sees ───────────────────────────────────────────────────────

def features(tx) -> dict:
    """Sparse features of one exported row, for the classical model."""
    f = {f"direction={tx.get('direction')}": 1, f"code={tx.get('code')}": 1,
         f"role={tx.get('account_role') or 'none'}": 1,
         f"weekday={tx.get('weekday')}": 1,
         f"hour={'none' if tx.get('hour') is None else tx['hour']}": 1}
    amount = tx.get("amount")
    if amount is not None:
        f["log_amount"] = math.log1p(amount)
        f["round_amount"] = 1 if float(amount).is_integer() else 0
    if tx.get("pot_hint"):
        f["pot_hint"] = 1
    if tx.get("counterparty_iban"):
        f[f"iban={tx['counterparty_iban']}"] = 1
    for w in WORD.findall((tx.get("counterparty") or "").lower()):
        f[f"cp:{w}"] = 1
    for w in WORD.findall((tx.get("remittance") or "").lower()):
        f[f"rem:{w}"] = 1
    return f


def row_text(tx) -> str:
    """One exported row as text, for the local encoder (Tier 0: raw text)."""
    day = tx.get("weekday")
    parts = [f"{tx.get('direction')} {tx.get('amount') or 0:.2f} EUR",
             tx.get("counterparty") or "", tx.get("remittance") or "",
             f"code {tx.get('code')}",
             WEEKDAYS[day] if isinstance(day, int) and 0 <= day < 7 else ""]
    if tx.get("account_role"):
        parts.append(f"account {tx['account_role']}")
    if tx.get("pot_hint"):
        parts.append("same amount as a transfer in from savings")
    return " | ".join(p for p in parts if p)


# ── folds, temperature, mask ────────────────────────────────────────────────

def month_folds(labels, k=FOLDS):
    ordered = sorted(set(labels), key=se.month_key)
    return {m: i % k for i, m in enumerate(ordered)}


def softmax(logits, temperature=1.0):
    finite = [x for x in logits if x != -math.inf]
    top = max(finite) if finite else 0.0
    exps = [0.0 if x == -math.inf else math.exp((x - top) / temperature) for x in logits]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def _nll(logits, gold, t):
    return -sum(math.log(max(softmax(row, t)[g], 1e-12)) for row, g in zip(logits, gold))


def fit_temperature(logits, gold, low=0.05, high=20.0):
    """The temperature minimising the log loss on (logits, gold index), by
    golden-section search over log T."""
    if not logits:
        return 1.0
    a, b = math.log(low), math.log(high)
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    for _ in range(60):
        if _nll(logits, gold, math.exp(c)) < _nll(logits, gold, math.exp(d)):
            b = d
        else:
            a = c
        c, d = b - g * (b - a), a + g * (b - a)
    return math.exp((a + b) / 2)


def masked(logits, classes, allowed):
    return [x if c in allowed else -math.inf for x, c in zip(logits, classes)]


# ── the run ─────────────────────────────────────────────────────────────────

def _close(model):
    if hasattr(model, "close"):
        model.close()


def run_arm(rows, make_model, split_kind, folds=FOLDS):
    """({id: {"category", "confidence"}} for every routed row, info).

    `make_model()` returns an object with fit(rows) and logits(rows) ->
    (classes, [[logit per class]]). No fit ever sees a test month.
    """
    split = se.split_months([r["label"] for r in rows], split_kind)
    train = [r for r in rows if split[r["label"]] == "train"]
    test_routed = [r for r in rows if split[r["label"]] == "test" and r["routed"]]
    allowed = defaultdict(set)
    for r in train:
        allowed[r["block"]].add(r["truth"])

    fold_of = month_folds([r["label"] for r in train], folds)
    oof = []                                    # (row, classes, logits)
    for f in sorted(set(fold_of.values())):
        fit_rows = [r for r in train if fold_of[r["label"]] != f]
        held = [r for r in train if fold_of[r["label"]] == f]
        if not fit_rows or not held:
            continue
        model = make_model()
        model.fit(fit_rows)
        classes, logits = model.logits(held)
        _close(model)
        oof += [(r, classes, masked(lg, classes, allowed[r["block"]])) for r, lg in zip(held, logits)]

    cal_logits, cal_gold = [], []
    for r, classes, lg in oof:
        if r["truth"] in classes and lg[classes.index(r["truth"])] != -math.inf:
            cal_logits.append(lg)
            cal_gold.append(classes.index(r["truth"]))
    temperature = fit_temperature(cal_logits, cal_gold)

    def answer(classes, lg):
        p = softmax(lg, temperature)
        best = max(range(len(p)), key=p.__getitem__)
        return {"category": classes[best], "confidence": round(p[best], 6)}

    preds = {r["id"]: answer(classes, lg) for r, classes, lg in oof if r["routed"]}
    model = make_model()
    model.fit(train)
    classes, logits = model.logits(test_routed)
    _close(model)
    for r, lg in zip(test_routed, logits):
        preds[r["id"]] = answer(classes, masked(lg, classes, allowed[r["block"]]))
    info = {"temperature": temperature, "train_rows": len(train), "calibration_rows": len(cal_gold),
            "test_rows": len(test_routed)}
    return preds, info


# ── the models ──────────────────────────────────────────────────────────────

class ClassicalModel:
    """Logistic regression over features(); C fixed before any run."""

    C = 1.0

    def fit(self, rows):
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.linear_model import LogisticRegression
        self.vec = DictVectorizer()
        x = self.vec.fit_transform([features(r["tx"]) for r in rows])
        self.clf = LogisticRegression(C=self.C, max_iter=5000)
        self.clf.fit(x, [r["truth"] for r in rows])

    def logits(self, rows):
        classes = list(self.clf.classes_)
        if not rows:
            return classes, []
        x = self.vec.transform([features(r["tx"]) for r in rows])
        scores = self.clf.decision_function(x)
        if len(classes) == 2:                    # one column: the second class
            scores = [[0.0, float(s)] for s in scores]
        return classes, [[float(v) for v in row] for row in scores]


def _laya(args):
    import shadow_laya
    return shadow_laya.factory(args)


ARMS = {"classical": lambda args: ClassicalModel, "laya": _laya}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("arm")
    parser.add_argument("--export", required=True, help="the private export (0600)")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--splits", default=",".join(se.SPLITS))
    parser.add_argument("--device", default="cuda", help="laya: cuda or cpu")
    parser.add_argument("--base", help="laya: the downloaded base checkpoint (see shadow_laya.py)")
    parser.add_argument("--epochs", type=int, default=4, help="laya: fine-tune epochs")
    args = parser.parse_args(argv)
    if args.arm not in ARMS:
        print(f"stopped: unknown arm (known: {', '.join(ARMS)})")
        return 2
    try:
        header, rows = se.read_jsonl(args.export)
    except se.InputError as exc:
        print(f"stopped: {exc}")
        return 2
    if header.get("kind") != "export":
        print("stopped: not an export file (eval_categoriser.py --export-out)")
        return 2
    if args.arm == "laya" and not args.base:
        print("stopped: laya needs --base, the downloaded checkpoint (see shadow_laya.py)")
        return 2
    try:
        make_model = ARMS[args.arm](args)
    except Exception as exc:                    # noqa: BLE001 - NotIsolated and import errors
        print(f"stopped: {type(exc).__name__}: {exc}" if type(exc).__name__ == "NotIsolated"
              else f"stopped: {type(exc).__name__} while preparing the {args.arm} arm")
        return 2
    print(f"export: {len(rows)} rows, {sum(1 for r in rows if r['routed'])} routed, "
          f"{len({r['label'] for r in rows})} months")
    for split in args.splits.split(","):
        preds, info = run_arm(rows, make_model, split)
        path = os.path.join(args.out_dir, f"pred-{args.arm}-{split}.jsonl")
        se.write_private_jsonl(path, {"kind": "predictions", "arm": args.arm, "split": split,
                                      "local": True, "fingerprint": header["fingerprint"],
                                      "temperature": info["temperature"]},
                               [{"id": i, **p} for i, p in sorted(preds.items())])
        print(f"{split}: trained on {info['train_rows']} rows, temperature {info['temperature']:.2f} "
              f"from {info['calibration_rows']} out-of-fold rows, {info['test_rows']} test rows; "
              f"{len(preds)} answers written to {path} (0600, not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
