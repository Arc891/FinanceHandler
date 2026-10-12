#!/usr/bin/env python3
"""
Shadow-eval of candidate categorisers against Sonnet (jev-investigation.md
§5.1 step 1, scored by the pre-registered criteria of §5.3).

Only the rows today's rules send to the AI are scored, in the test months of
two splits of the hand-checked 2024/2025 months:

  alternating  by sheet month, every other month: 10 train, 9 test
  forward      train up to 08/2025, test 09/2025-12/2025; decides when the
               two splits disagree

Files (all JSON lines, 0600, a header line first):

  rows.jsonl          eval_categoriser.py --rows-out, on the Pi: one line per
                      scored row with its month, block, key group, true
                      category and whether the rules sent it to the AI. No
                      transaction text.
  pred-<arm>[-<split>].jsonl
                      one line per routed row: id, category, confidence. A
                      trained arm writes one file per split, with
                      out-of-fold answers on that split's train months; an
                      untrained arm (sonnet, jev) writes one for both.

Every file carries the fingerprint of the matching that produced the rows,
so files from different exports or sheets are never joined.

Each candidate's threshold is fitted on the train months: the lowest at
which it writes no more rows wrong and unflagged than Sonnet does there.
Sonnet keeps production's threshold. Then, on the test months:

  (a) rows written wrong and unflagged: no more than Sonnet's
  (b) rows needing the user (flagged plus wrong unflagged): no more than Sonnet's
  (c) accuracy above Sonnet's by McNemar p < 0.05 and by at least 5 points
  (d) no true category with 20 or more rows more than 5 points below Sonnet

(a)-(c) are checked again on the post-move test months (02/2025 onward); a
candidate switches only if all hold in both. A local arm that holds (a) and
(b) without switching is recorded as the Tier-0 option.

The report holds counts, percentages, month labels and category names only.

    venv/bin/python scripts/shadow_eval.py --rows rows.jsonl \\
        --sonnet pred-sonnet.jsonl pred-laya-alternating.jsonl \\
        pred-laya-forward.jsonl pred-jev.jsonl
"""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from math import comb

POST_MOVE_FROM = "02/2025"
FORWARD_TEST_FROM = "09/2025"
SPLITS = ("alternating", "forward")
SONNET_THRESHOLD = 0.75          # AI_CONFIDENCE_THRESHOLD in production
ALPHA = 0.05
MIN_GAIN_PP = 5.0
MIN_CATEGORY_N = 20
MAX_CATEGORY_DROP_PP = 5.0
NAME_MAX = 40


class InputError(Exception):
    """A file the report cannot use; the message is written here, never row content."""


# ── months and splits ───────────────────────────────────────────────────────

def month_key(label):
    return (int(label[3:]), int(label[:2]))


def post_move(label) -> bool:
    return month_key(label) >= month_key(POST_MOVE_FROM)


def split_months(labels, kind, forward_from=FORWARD_TEST_FROM):
    """{label: "train" | "test"} for the given sheet months."""
    ordered = sorted(set(labels), key=month_key)
    if kind == "alternating":
        return {m: "train" if i % 2 == 0 else "test" for i, m in enumerate(ordered)}
    if kind == "forward":
        cut = month_key(forward_from)
        return {m: "test" if month_key(m) >= cut else "train" for m in ordered}
    raise ValueError(f"unknown split {kind!r}")


# ── files ───────────────────────────────────────────────────────────────────

def fingerprint(keys) -> str:
    """A short hash of the matched rows' keys, in order; names nothing."""
    return hashlib.sha256(repr(list(keys)).encode()).hexdigest()[:16]


def write_private_jsonl(path, header, rows):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        raise InputError(f"{os.path.basename(path)} does not exist") from None
    except json.JSONDecodeError:
        raise InputError(f"{os.path.basename(path)} is not JSON lines") from None
    if not lines:
        raise InputError(f"{os.path.basename(path)} is empty")
    return lines[0], lines[1:]


def load_run(rows_path, sonnet_path, arm_paths):
    """(rows, sonnet predictions, [arm]) with every fingerprint checked.

    An arm is {"name", "local", "splits": {split: {id: prediction}}}; an
    untrained arm's single file serves both splits.
    """
    header, rows = read_jsonl(rows_path)
    if header.get("kind") != "rows":
        raise InputError(f"{os.path.basename(rows_path)} is not a rows file")
    fp = header.get("fingerprint")

    def predictions(path):
        h, body = read_jsonl(path)
        if h.get("kind") != "predictions":
            raise InputError(f"{os.path.basename(path)} is not a predictions file")
        if h.get("fingerprint") != fp:
            raise InputError(f"{os.path.basename(path)} comes from another matching "
                             "(fingerprint differs from the rows file)")
        return h, {p["id"]: {"category": p.get("category"),
                             "confidence": float(p.get("confidence") or 0.0)} for p in body}

    _, sonnet = predictions(sonnet_path)
    arms = {}
    for path in arm_paths:
        h, preds = predictions(path)
        name = h.get("arm") or os.path.basename(path)
        arm = arms.setdefault(name, {"name": name, "local": bool(h.get("local")), "splits": {}})
        split = h.get("split", "any")
        if split == "any":
            for s in SPLITS:
                arm["splits"].setdefault(s, preds)
        elif split in SPLITS:
            arm["splits"][split] = preds
        else:
            raise InputError(f"{os.path.basename(path)}: unknown split")
    return rows, sonnet, list(arms.values())


# ── scoring ─────────────────────────────────────────────────────────────────

def score_rows(rows, preds):
    """{id: correct}. Rows sharing a key group are scored as a multiset, so the
    arbitrary pairing of export and sheet rows inside a group costs nothing.
    Only the given rows take part; a missing prediction is wrong."""
    groups = defaultdict(list)
    for r in rows:
        groups[r["group"]].append(r)
    correct = {}
    for members in groups.values():
        remaining = Counter(r["truth"] for r in members)
        for r in members:
            cat = (preds.get(r["id"]) or {}).get("category")
            if cat is not None and remaining[cat] > 0:
                remaining[cat] -= 1
                correct[r["id"]] = True
            else:
                correct[r["id"]] = False
    return correct


def is_flagged(prediction, threshold) -> bool:
    if not prediction or prediction.get("category") is None:
        return True
    return prediction["confidence"] < threshold


def wrong_unflagged(preds, correct, threshold, ids=None):
    ids = correct.keys() if ids is None else ids
    return sum(1 for i in ids if not correct[i] and not is_flagged(preds.get(i), threshold))


def flagged_count(preds, threshold, ids):
    return sum(1 for i in ids if is_flagged(preds.get(i), threshold))


def fit_threshold(preds, correct, target_wrong_unflagged):
    """The lowest threshold at which no more than `target_wrong_unflagged` of
    the rows in `correct` are written wrong and unflagged. Flagging only grows
    with the threshold, so the lowest one also flags the fewest rows."""
    confs = sorted({preds[i]["confidence"] for i in correct
                    if preds.get(i) and preds[i].get("category") is not None})
    for t in [0.0] + confs:
        if wrong_unflagged(preds, correct, t) <= target_wrong_unflagged:
            return t
    return (confs[-1] if confs else 0.0) + 1e-6


def mcnemar_exact(b, c) -> float:
    """Two-sided exact McNemar p for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _band(confidence):
    return "high" if confidence >= 0.85 else "medium" if confidence >= 0.5 else "low"


def _side(rows, preds, correct, threshold):
    ids = [r["id"] for r in rows]
    wu = wrong_unflagged(preds, correct, threshold, ids)
    fl = flagged_count(preds, threshold, ids)
    return {"n": len(ids), "correct": sum(correct[i] for i in ids),
            "flagged": fl, "wrong_unflagged": wu, "needing_you": fl + wu}


def compare(rows, cand, cand_t, sonnet, sonnet_t):
    """The figures and checks (a)-(d) on `rows` (routed rows of test months)."""
    c_ok, s_ok = score_rows(rows, cand), score_rows(rows, sonnet)
    c_side, s_side = _side(rows, cand, c_ok, cand_t), _side(rows, sonnet, s_ok, sonnet_t)
    n = len(rows)
    c_acc = 100 * c_side["correct"] / n if n else 0.0
    s_acc = 100 * s_side["correct"] / n if n else 0.0
    b = sum(1 for r in rows if c_ok[r["id"]] and not s_ok[r["id"]])
    c = sum(1 for r in rows if s_ok[r["id"]] and not c_ok[r["id"]])
    p = mcnemar_exact(b, c)

    per_month = {}
    for label in sorted({r["label"] for r in rows}, key=month_key):
        sel = [r for r in rows if r["label"] == label]
        per_month[label] = {"candidate": _side(sel, cand, c_ok, cand_t),
                            "sonnet": _side(sel, sonnet, s_ok, sonnet_t)}

    categories = {}
    by_truth = defaultdict(list)
    for r in rows:
        by_truth[r["truth"]].append(r["id"])
    for cat, ids in by_truth.items():
        categories[cat] = {"n": len(ids),
                           "candidate": 100 * sum(c_ok[i] for i in ids) / len(ids),
                           "sonnet": 100 * sum(s_ok[i] for i in ids) / len(ids)}

    bands = {}
    for name, preds, ok in (("candidate", cand, c_ok), ("sonnet", sonnet, s_ok)):
        tally = defaultdict(lambda: [0, 0])
        for r in rows:
            pr = preds.get(r["id"])
            if pr and pr.get("category") is not None:
                t = tally[_band(pr["confidence"])]
                t[0] += 1
                t[1] += ok[r["id"]]
        bands[name] = {k: tuple(v) for k, v in tally.items()}

    checks = {
        "a": c_side["wrong_unflagged"] <= s_side["wrong_unflagged"],
        "b": c_side["needing_you"] <= s_side["needing_you"],
        "c": p < ALPHA and c_acc - s_acc >= MIN_GAIN_PP,
        "d": all(v["candidate"] >= v["sonnet"] - MAX_CATEGORY_DROP_PP
                 for v in categories.values() if v["n"] >= MIN_CATEGORY_N),
    }
    return {"n": n, "months": len(per_month), "candidate": c_side, "sonnet": s_side,
            "candidate_accuracy": c_acc, "sonnet_accuracy": s_acc,
            "accuracy_gain_pp": c_acc - s_acc, "discordant": (b, c), "mcnemar_p": p,
            "per_month": per_month, "categories": categories, "bands": bands,
            "checks": checks}


def _verdict(overall, post, local):
    post_ok = post is None or all(post["checks"][k] for k in "abc")
    if all(overall["checks"].values()) and post_ok:
        return "switch"
    if local and overall["checks"]["a"] and overall["checks"]["b"]:
        return "tier0-option"
    return "no-switch"


def evaluate(rows, sonnet, arm, sonnet_threshold=SONNET_THRESHOLD):
    """Both splits for one arm, and the verdict (the forward split decides
    when they disagree)."""
    labels = [r["label"] for r in rows]
    routed = [r for r in rows if r["routed"]]
    out = {"arm": arm["name"], "local": arm["local"], "splits": {}}
    for kind in SPLITS:
        if kind not in arm["splits"]:
            continue
        cand = arm["splits"][kind]
        split = split_months(labels, kind)
        train = [r for r in routed if split[r["label"]] == "train"]
        test = [r for r in routed if split[r["label"]] == "test"]
        s_train_ok = score_rows(train, sonnet)
        target = wrong_unflagged(sonnet, s_train_ok, sonnet_threshold)
        t = fit_threshold(cand, score_rows(train, cand), target)
        overall = compare(test, cand, t, sonnet, sonnet_threshold)
        post_rows = [r for r in test if post_move(r["label"])]
        post = compare(post_rows, cand, t, sonnet, sonnet_threshold) if post_rows else None
        out["splits"][kind] = {
            "threshold": t, "train_months": sorted({r["label"] for r in train}, key=month_key),
            "test_months": sorted({r["label"] for r in test}, key=month_key),
            "sonnet_train_wrong_unflagged": target,
            "overall": overall, "post_move": post,
            "verdict": _verdict(overall, post, arm["local"])}
    verdicts = {k: v["verdict"] for k, v in out["splits"].items()}
    if "forward" in verdicts:
        out["verdict"] = verdicts["forward"]
        out["decided_by"] = "both" if len(set(verdicts.values())) == 1 else "forward"
    else:
        out["verdict"] = next(iter(verdicts.values()), "no-switch")
        out["decided_by"] = next(iter(verdicts), "none")
    return out


# ── the report ──────────────────────────────────────────────────────────────

def _name(s):
    s = "(none)" if s is None else str(s)
    return s if len(s) <= NAME_MAX else s[:NAME_MAX] + "..."


def _pct(ok, n):
    return f"{ok}/{n} = {100 * ok / n:.1f}%" if n else "0/0"


def _fmt_compare(res, indent="    ", full=True):
    c, s = res["candidate"], res["sonnet"]
    m = max(res["months"], 1)
    ck = res["checks"]
    yes = {True: "pass", False: "FAIL"}
    lines = [
        f"{indent}rows {res['n']} over {res['months']} month(s)",
        f"{indent}accuracy: candidate {_pct(c['correct'], c['n'])}, sonnet {_pct(s['correct'], s['n'])}, "
        f"gain {res['accuracy_gain_pp']:+.1f} pp",
        f"{indent}(a) wrong unflagged: candidate {c['wrong_unflagged']} ({c['wrong_unflagged'] / m:.1f}/month), "
        f"sonnet {s['wrong_unflagged']} ({s['wrong_unflagged'] / m:.1f}/month): {yes[ck['a']]}",
        f"{indent}(b) needing you: candidate {c['needing_you']} ({c['needing_you'] / m:.1f}/month, "
        f"{c['flagged']} flagged), sonnet {s['needing_you']} ({s['needing_you'] / m:.1f}/month, "
        f"{s['flagged']} flagged): {yes[ck['b']]}",
        f"{indent}(c) McNemar {res['discordant'][0]} vs {res['discordant'][1]} discordant, "
        f"p = {res['mcnemar_p']:.4f}, gain {res['accuracy_gain_pp']:+.1f} pp: {yes[ck['c']]}",
    ]
    if "d" in ck and full:
        big = {k: v for k, v in res["categories"].items() if v["n"] >= MIN_CATEGORY_N}
        lines.append(f"{indent}(d) categories with n >= {MIN_CATEGORY_N}: {yes[ck['d']]}")
        for cat, v in sorted(big.items(), key=lambda kv: -kv[1]["n"]):
            lines.append(f"{indent}    {_name(cat)}: n {v['n']}, candidate {v['candidate']:.1f}%, "
                         f"sonnet {v['sonnet']:.1f}% ({v['candidate'] - v['sonnet']:+.1f})")
    if full:
        for who in ("candidate", "sonnet"):
            b = res["bands"][who]
            lines.append(f"{indent}{who} by band: " + ", ".join(
                f"{k} {_pct(b[k][1], b[k][0])}" for k in ("high", "medium", "low") if k in b))
        lines.append(f"{indent}per month (wrong unflagged / needing you), candidate vs sonnet:")
        for label, v in res["per_month"].items():
            lines.append(f"{indent}    {label}: {v['candidate']['wrong_unflagged']}/{v['candidate']['needing_you']}"
                         f" vs {v['sonnet']['wrong_unflagged']}/{v['sonnet']['needing_you']}")
    return lines


def format_evaluation(ev):
    kind = "local" if ev["local"] else "hosted"
    lines = [f"arm {ev['arm']} ({kind})"]
    for split, s in ev["splits"].items():
        lines.append(f"  split {split}: train {len(s['train_months'])} month(s), test "
                     f"{', '.join(s['test_months'])}")
        lines.append(f"    threshold {s['threshold']:.3f} (sonnet wrong unflagged on train months: "
                     f"{s['sonnet_train_wrong_unflagged']})")
        lines += _fmt_compare(s["overall"])
        if s["post_move"]:
            lines.append("    post-move test months:")
            lines += _fmt_compare(s["post_move"], indent="      ", full=False)
        else:
            lines.append("    post-move test months: none")
        lines.append(f"    split verdict: {s['verdict']}")
    lines.append(f"  verdict: {ev['verdict']} (decided by {ev['decided_by']})")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--rows", required=True, help="rows file from eval_categoriser.py --rows-out")
    parser.add_argument("--sonnet", required=True, help="Sonnet's predictions file")
    parser.add_argument("--sonnet-threshold", type=float, default=SONNET_THRESHOLD)
    parser.add_argument("arms", nargs="+", help="candidate predictions files")
    args = parser.parse_args(argv)
    try:
        rows, sonnet, arms = load_run(args.rows, args.sonnet, args.arms)
    except InputError as exc:
        print(f"stopped: {exc}")
        return 2
    routed = [r for r in rows if r["routed"]]
    print(f"rows {len(rows)}, sent to the AI by today's rules {len(routed)}")
    for arm in arms:
        print("")
        for line in format_evaluation(evaluate(rows, sonnet, arm, args.sonnet_threshold)):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
