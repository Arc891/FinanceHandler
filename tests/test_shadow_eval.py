"""
Tests for scripts/shadow_eval.py (jev-investigation.md §5.1 step 1, §5.3).

The splits, the files that pass between the Pi and the workstation, the
multiset scoring, the threshold fit, McNemar's test and the pre-registered
checks (a)-(d) with the post-move and forward-split rules. All synthetic.
"""

import json
import os
import stat

import pytest

import shadow_eval as se

MONTHS = [f"{m:02d}/2024" for m in range(6, 13)] + [f"{m:02d}/2025" for m in range(1, 13)]


# ── splits ──────────────────────────────────────────────────────────────────

def test_alternating_split_trains_on_ten_and_tests_on_nine_months():
    split = se.split_months(MONTHS, "alternating")
    assert sum(1 for v in split.values() if v == "train") == 10
    assert sum(1 for v in split.values() if v == "test") == 9
    assert split["06/2024"] == "train" and split["07/2024"] == "test"


def test_alternating_split_orders_by_year_then_month_not_by_text():
    split = se.split_months(["01/2025", "12/2024", "11/2024"], "alternating")
    assert split == {"11/2024": "train", "12/2024": "test", "01/2025": "train"}


def test_forward_split_tests_from_september_2025():
    split = se.split_months(MONTHS, "forward")
    assert [m for m in MONTHS if split[m] == "test"] == ["09/2025", "10/2025", "11/2025", "12/2025"]
    assert split["08/2025"] == "train" and split["06/2024"] == "train"


def test_an_unknown_split_is_refused():
    with pytest.raises(ValueError):
        se.split_months(MONTHS, "random")


def test_post_move_months_start_in_february_2025():
    assert not se.post_move("01/2025")
    assert se.post_move("02/2025") and se.post_move("12/2025")
    assert not se.post_move("12/2024")


# ── files ───────────────────────────────────────────────────────────────────

def test_private_files_are_0600_and_round_trip(tmp_path):
    path = tmp_path / "rows.jsonl"
    se.write_private_jsonl(str(path), {"kind": "rows", "fingerprint": "abc"},
                           [{"id": 0, "truth": "Boodschappen"}])
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    header, rows = se.read_jsonl(str(path))
    assert header == {"kind": "rows", "fingerprint": "abc"}
    assert rows == [{"id": 0, "truth": "Boodschappen"}]


def test_rewriting_a_private_file_keeps_it_0600(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text("old\n")
    os.chmod(path, 0o644)
    se.write_private_jsonl(str(path), {}, [])
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_fingerprint_depends_on_order_and_content_and_is_short():
    a = se.fingerprint([("03/2024", "2024-03-01", "1.00", "expenses")])
    b = se.fingerprint([("03/2024", "2024-03-01", "1.01", "expenses")])
    assert a != b and len(a) == 16
    assert "2024" not in a


def test_predictions_from_another_matching_are_refused(tmp_path):
    rows = tmp_path / "rows.jsonl"
    pred = tmp_path / "pred.jsonl"
    se.write_private_jsonl(str(rows), {"kind": "rows", "fingerprint": "aaaa"}, [])
    se.write_private_jsonl(str(pred), {"kind": "predictions", "arm": "x", "split": "any",
                                       "fingerprint": "bbbb"}, [])
    with pytest.raises(se.InputError):
        se.load_run(str(rows), str(pred), [])


# ── scoring ─────────────────────────────────────────────────────────────────

def row(i, truth, label="07/2024", group=None, routed=True, block="expenses"):
    return {"id": i, "label": label, "block": block, "group": i if group is None else group,
            "truth": truth, "routed": routed}


def pred(category, confidence=0.9):
    return {"category": category, "confidence": confidence}


def test_a_shared_key_group_scores_as_a_multiset():
    rows = [row(0, "A", group=7), row(1, "B", group=7)]
    correct = se.score_rows(rows, {0: pred("B"), 1: pred("A")})
    assert correct == {0: True, 1: True}
    correct = se.score_rows(rows, {0: pred("A"), 1: pred("A")})
    assert sorted(correct.values()) == [False, True]


def test_a_missing_prediction_is_wrong():
    assert se.score_rows([row(0, "A")], {}) == {0: False}


def test_a_row_is_flagged_below_the_threshold_or_without_an_answer():
    assert se.is_flagged(pred("A", 0.6), 0.75)
    assert not se.is_flagged(pred("A", 0.9), 0.75)
    assert not se.is_flagged(pred("A", 0.75), 0.75)
    assert se.is_flagged(None, 0.0)
    assert se.is_flagged(pred(None, 0.99), 0.0)


# ── threshold fit ───────────────────────────────────────────────────────────

def test_threshold_is_the_lowest_that_keeps_wrong_unflagged_at_sonnets_level():
    # confidences: wrong 0.95, right 0.9, wrong 0.8, right 0.7
    preds = {0: pred("X", 0.95), 1: pred("A", 0.9), 2: pred("X", 0.8), 3: pred("A", 0.7)}
    correct = {0: False, 1: True, 2: False, 3: True}
    assert se.fit_threshold(preds, correct, target_wrong_unflagged=1) == 0.9
    assert se.fit_threshold(preds, correct, target_wrong_unflagged=2) == 0.0
    t = se.fit_threshold(preds, correct, target_wrong_unflagged=0)
    assert t > 0.95                     # everything flagged
    assert se.wrong_unflagged(preds, correct, t) == 0


def test_threshold_fit_counts_only_answered_rows_as_unflagged():
    preds = {0: pred(None, 0.0), 1: pred("A", 0.5)}
    assert se.fit_threshold(preds, {0: False, 1: True}, target_wrong_unflagged=0) == 0.0


# ── McNemar ─────────────────────────────────────────────────────────────────

def test_mcnemar_exact_known_values():
    assert se.mcnemar_exact(0, 0) == 1.0
    assert se.mcnemar_exact(5, 5) == 1.0
    assert se.mcnemar_exact(0, 6) == pytest.approx(2 / 64)      # 0.03125
    assert se.mcnemar_exact(1, 9) == pytest.approx(2 * 11 / 1024)
    assert se.mcnemar_exact(9, 1) == se.mcnemar_exact(1, 9)


# ── the pre-registered checks ───────────────────────────────────────────────

def world(n_per_month, sonnet_right, cand_right, months=("07/2024", "03/2025"),
          sonnet_conf=0.9, cand_conf=0.9, category="Boodschappen"):
    """Rows over `months`; Sonnet and the candidate right on the first k of each month."""
    rows, sonnet, cand = [], {}, {}
    i = 0
    for label in months:
        for k in range(n_per_month):
            rows.append(row(i, category, label=label))
            sonnet[i] = pred(category if k < sonnet_right else "Fout", sonnet_conf)
            cand[i] = pred(category if k < cand_right else "Fout", cand_conf)
            i += 1
    return rows, sonnet, cand


def test_a_clearly_better_candidate_passes_every_check():
    rows, sonnet, cand = world(30, sonnet_right=15, cand_right=27)
    res = se.compare(rows, cand, 0.0, sonnet, 0.75)
    assert res["checks"] == {"a": True, "b": True, "c": True, "d": True}


def test_more_wrong_unflagged_rows_fail_check_a():
    rows, sonnet, cand = world(30, sonnet_right=15, cand_right=27, sonnet_conf=0.6)
    res = se.compare(rows, cand, 0.5, sonnet, 0.75)
    assert res["checks"]["a"] is False      # Sonnet flags everything, so 0 wrong unflagged


def test_flagging_more_rows_than_sonnet_needs_you_more_and_fails_check_b():
    rows, sonnet, cand = world(30, sonnet_right=29, cand_right=29)
    res = se.compare(rows, cand, 0.99, sonnet, 0.75)    # candidate flags all
    assert res["checks"]["b"] is False


def test_a_small_gain_fails_check_c_even_when_significant_by_count():
    rows, sonnet, cand = world(200, sonnet_right=100, cand_right=108)
    res = se.compare(rows, cand, 0.0, sonnet, 0.75)
    assert res["accuracy_gain_pp"] == pytest.approx(4.0)
    assert res["checks"]["c"] is False


def test_a_large_gain_on_few_rows_fails_check_c_on_mcnemar():
    rows, sonnet, cand = world(3, sonnet_right=1, cand_right=2)
    res = se.compare(rows, cand, 0.0, sonnet, 0.75)
    assert res["accuracy_gain_pp"] > 5 and res["mcnemar_p"] >= 0.05
    assert res["checks"]["c"] is False


def test_a_category_of_twenty_rows_falling_over_five_points_fails_check_d():
    rows, sonnet, cand = world(30, sonnet_right=10, cand_right=28)
    i = len(rows)
    for k in range(20):                 # a second category, Sonnet better there
        rows.append(row(i, "Huur", label="07/2024"))
        sonnet[i] = pred("Huur", 0.9)
        cand[i] = pred("Huur" if k < 18 else "Fout", 0.9)
        i += 1
    res = se.compare(rows, cand, 0.0, sonnet, 0.75)
    assert res["checks"]["d"] is False
    assert res["categories"]["Huur"]["n"] == 20


def test_a_category_under_twenty_rows_is_not_held_to_check_d():
    rows, sonnet, cand = world(30, sonnet_right=10, cand_right=28)
    i = len(rows)
    for k in range(19):
        rows.append(row(i, "Huur", label="07/2024"))
        sonnet[i] = pred("Huur", 0.9)
        cand[i] = pred("Fout", 0.9)
        i += 1
    assert se.compare(rows, cand, 0.0, sonnet, 0.75)["checks"]["d"] is True


def test_per_month_figures_are_reported_for_each_test_month():
    rows, sonnet, cand = world(10, sonnet_right=5, cand_right=8)
    res = se.compare(rows, cand, 0.0, sonnet, 0.75)
    assert set(res["per_month"]) == {"07/2024", "03/2025"}
    m = res["per_month"]["07/2024"]
    assert m["candidate"]["wrong_unflagged"] == 2 and m["sonnet"]["wrong_unflagged"] == 5
    assert m["candidate"]["needing_you"] == 2 and m["sonnet"]["needing_you"] == 5


# ── evaluation: splits, post-move, verdicts ─────────────────────────────────

def full_world(cand_right_old, cand_right_new, sonnet_right=10, n=30, local=True):
    """Every month of MONTHS, all rows routed; the candidate's skill differs
    before and after the move."""
    rows, sonnet, cand = [], {}, {}
    i = 0
    for label in MONTHS:
        good = cand_right_new if se.post_move(label) else cand_right_old
        for k in range(n):
            rows.append(row(i, "Boodschappen", label=label))
            sonnet[i] = pred("Boodschappen" if k < sonnet_right else "Fout", 0.9)
            cand[i] = pred("Boodschappen" if k < good else "Fout", 0.95 if k < good else 0.4)
            i += 1
    arm = {"name": "laya", "local": local,
           "splits": {"alternating": cand, "forward": cand}}
    return rows, sonnet, arm


def test_a_better_candidate_is_switched_to():
    rows, sonnet, arm = full_world(28, 28)
    out = se.evaluate(rows, sonnet, arm)
    assert out["verdict"] == "switch"
    assert out["splits"]["alternating"]["verdict"] == "switch"


def test_failing_the_post_move_months_blocks_a_switch():
    rows, sonnet, arm = full_world(30, 9)
    out = se.evaluate(rows, sonnet, arm)
    assert out["splits"]["alternating"]["post_move"]["checks"]["c"] is False
    assert out["verdict"] != "switch"


def test_a_local_arm_that_ties_is_the_tier0_option_not_a_switch():
    rows, sonnet, arm = full_world(10, 10)
    out = se.evaluate(rows, sonnet, arm)
    assert out["verdict"] == "tier0-option"


def test_a_hosted_arm_that_ties_is_no_switch():
    rows, sonnet, arm = full_world(10, 10, local=False)
    assert se.evaluate(rows, sonnet, arm)["verdict"] == "no-switch"


def test_the_forward_split_decides_when_the_splits_disagree():
    rows, sonnet, arm = full_world(28, 28)
    bad = {i: pred("Fout", 0.95) for i in arm["splits"]["forward"]}
    arm["splits"]["forward"] = bad
    out = se.evaluate(rows, sonnet, arm)
    assert out["splits"]["alternating"]["verdict"] == "switch"
    assert out["splits"]["forward"]["verdict"] == "no-switch"
    assert out["verdict"] == "no-switch" and out["decided_by"] == "forward"


def test_rows_the_rules_decide_are_never_scored():
    rows, sonnet, arm = full_world(28, 28)
    for r in rows:
        if r["label"] == "07/2024":
            r["routed"] = False
    out = se.evaluate(rows, sonnet, arm)
    assert "07/2024" not in out["splits"]["alternating"]["overall"]["per_month"]


def test_the_threshold_is_fitted_on_train_months_only():
    rows, sonnet, arm = full_world(28, 28)
    # poison the test months' confidences: a fit that looked at them would move
    split = se.split_months(MONTHS, "alternating")
    fitted = se.evaluate(rows, sonnet, arm)["splits"]["alternating"]["threshold"]
    for r in rows:
        if split[r["label"]] == "test":
            arm["splits"]["alternating"][r["id"]] = pred("Fout", 0.99)
    again = se.evaluate(rows, sonnet, arm)["splits"]["alternating"]["threshold"]
    assert fitted == again


# ── the printed report ──────────────────────────────────────────────────────

def test_the_report_holds_scores_and_category_names_only():
    rows, sonnet, arm = full_world(28, 28)
    text = "\n".join(se.format_evaluation(se.evaluate(rows, sonnet, arm)))
    assert "laya" in text and "verdict" in text
    assert "(a)" in text and "(d)" in text and "post-move" in text
    for r in rows[:3]:
        assert f'"id": {r["id"]}' not in text


def test_report_cli_end_to_end(tmp_path, capsys):
    rows, sonnet, arm = full_world(28, 28)
    rows_path, son_path = tmp_path / "rows.jsonl", tmp_path / "pred-sonnet.jsonl"
    fp = "f" * 16
    se.write_private_jsonl(str(rows_path), {"kind": "rows", "fingerprint": fp}, rows)
    se.write_private_jsonl(str(son_path), {"kind": "predictions", "arm": "sonnet", "split": "any",
                                           "fingerprint": fp},
                           [{"id": i, **p} for i, p in sonnet.items()])
    arm_paths = []
    for split, preds in arm["splits"].items():
        p = tmp_path / f"pred-laya-{split}.jsonl"
        se.write_private_jsonl(str(p), {"kind": "predictions", "arm": "laya", "split": split,
                                        "local": True, "fingerprint": fp},
                               [{"id": i, **q} for i, q in preds.items()])
        arm_paths.append(str(p))
    code = se.main(["--rows", str(rows_path), "--sonnet", str(son_path), *arm_paths])
    out = capsys.readouterr().out
    assert code == 0
    assert "laya" in out and "switch" in out
