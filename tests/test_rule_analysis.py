"""
Tests for the second pass of eval_categoriser --rules (rule_coverage.py).

What the bank row holds beyond name and text (time of day, transaction
code), which single feature best splits a mixed counterparty group (scored
leave-one-out, so a split that only fits the rows it was fitted on does not
win), whether pot transfers can be linked to the purchases they cover
(exact sums, several purchases per transfer), whether rules and groups hold
in each year, and the private draft rule file. The printed report keeps to
counts, category and feature names; thresholds, keywords, names and IBANs go
only to the 0600 draft. All data is synthetic.
"""

import os
import stat

import eval_categoriser as ev
import rule_coverage as rc
from fakes import expense_tx, income_tx

SAVINGS = "NL99SAVE0000000001"
PERSONAL = "NL98PERS0000000002"
VALID = {"expenses": {"Boodschappen", "Snacken", "Huishouden", "Cadeautjes", "Uit spaarpotje",
                      "Persoonlijk vrij geld", "Naar spaarpotjes", "Dates/uitjes", "Rekeningen",
                      "Zorgverzekering", "Goeie doelen"},
         "income": {"Spaarrekening", "Gift"}}


def tx(date, amount, name="Shop", rem="", out=True, iban="", code="8810 BEA", seq="1"):
    make = expense_tx if out else income_tx
    t = make(date_str=date, amount=f"-{amount}" if out else amount, name=name, rem=rem, seq=seq)
    t = {k: v for k, v in t.items() if k not in ("description", "category")}
    t["counterparty_iban"] = iban
    t["bank_transaction_code"] = {"description": code}
    return t


# ── what the data holds ─────────────────────────────────────────────────────

def test_time_of_day_is_read_from_a_card_payment_text():
    assert rc.tx_hour(tx("01-03-2024", "5.00", rem="BEA, Betaalpas NR:1 17.03.24/18:45 UTRECHT")) == 18
    assert rc.tx_hour(tx("01-03-2024", "5.00", rem="factuur 17.03 betaald")) is None
    assert rc.tx_hour(tx("01-03-2024", "5.00", rem="ref 12:34:56:78")) is None


def test_transaction_code_keeps_only_bank_shaped_codes():
    assert rc.tx_code(tx("01-03-2024", "5.00", code="8810 IDB")) == "IDB"
    assert rc.tx_code(tx("01-03-2024", "5.00", code="8810 Jolanda")) == "other"
    assert rc.tx_code({"bank_transaction_code": {}}) == "other"


def test_the_probe_counts_times_and_codes_per_category():
    pairs = [(tx("01-03-2024", "5.00", rem="x 01.03.24/12:10", code="1 BEA"), "Snacken"),
             (tx("04-03-2024", "5.00", code="1 IDB"), "Boodschappen"),
             (tx("05-03-2024", "5.00", code="1 IDB"), "Boodschappen")]
    probe = rc.feature_probe(pairs)
    assert probe["rows"] == 3 and probe["with_time"] == 1
    assert probe["codes"] == {"BEA": {"Snacken": 1}, "IDB": {"Boodschappen": 2}}


# ── splitting a mixed group ─────────────────────────────────────────────────

def test_amount_splits_dinner_from_a_snack():
    rows = ([(tx(f"0{d}-03-2024", a), "Boodschappen") for d, a in
             zip((4, 5, 6, 7, 8), ("31.00", "42.50", "35.00", "48.00", "39.90"))] +
            [(tx(f"1{d}-03-2024", a), "Snacken") for d, a in zip((1, 2, 3), ("3.50", "5.00", "4.20"))])
    split = rc.best_split(rows)
    assert split["best"] == "amount"
    assert split["features"]["amount"] == 1.0
    assert split["majority"] == 5 / 8
    assert "Snacken" in split["detail"] and "Boodschappen" in split["detail"]


def test_a_keyword_splits_premium_from_bills():
    rows = [(tx(f"0{d}-03-2024", a, rem=r), c) for d, a, r, c in (
        (4, "100.00", "premie maart", "Zorgverzekering"), (5, "30.00", "premie april", "Zorgverzekering"),
        (6, "100.00", "premie mei", "Zorgverzekering"), (7, "30.00", "premie juni", "Zorgverzekering"),
        (4, "30.00", "nota eigen risico", "Rekeningen"), (5, "100.00", "nota eigen risico", "Rekeningen"),
        (6, "30.00", "nota eigen risico", "Rekeningen"), (7, "100.00", "nota eigen risico", "Rekeningen"))]
    split = rc.best_split(rows)
    assert split["best"] == "keyword" and split["features"]["keyword"] == 1.0
    # Every word of either text splits perfectly; the tie goes alphabetically.
    assert "'eigen'" in split["detail"]


def test_weekend_splits_outings_from_groceries():
    weekend = ("02-03-2024", "03-03-2024", "09-03-2024", "10-03-2024")
    weekday = ("04-03-2024", "05-03-2024", "06-03-2024", "07-03-2024")
    amounts = ("10.00", "20.00", "10.00", "20.00")
    rows = ([(tx(d, a), "Dates/uitjes") for d, a in zip(weekend, amounts)] +
            [(tx(d, a), "Boodschappen") for d, a in zip(weekday, reversed(amounts))])
    split = rc.best_split(rows)
    assert split["best"] == "weekend" and split["features"]["weekend"] == 1.0


def test_time_of_day_splits_lunch_snacks_from_dinner():
    rows = [(tx("04-03-2024", a, rem=f"x 04.03.24/{h}:05"), c) for a, h, c in (
        ("10.00", 12, "Snacken"), ("20.00", 13, "Snacken"), ("10.00", 12, "Snacken"),
        ("20.00", 18, "Boodschappen"), ("10.00", 19, "Boodschappen"), ("20.00", 20, "Boodschappen"))]
    split = rc.best_split(rows)
    assert split["best"] == "time of day" and split["features"]["time of day"] == 1.0


def test_a_booking_habit_that_changed_between_years_splits_by_year():
    """Same shop, same amounts, same text: only the year tells them apart."""
    rows = [(tx(d, a, rem="same text"), c) for d, a, c in (
        ("04-03-2024", "10.00", "Huishouden"), ("05-03-2024", "20.00", "Huishouden"),
        ("06-03-2024", "10.00", "Huishouden"), ("04-03-2025", "20.00", "Cadeautjes"),
        ("05-03-2025", "10.00", "Cadeautjes"), ("06-03-2025", "20.00", "Cadeautjes"))]
    split = rc.best_split(rows)
    assert split["best"] == "year" and split["features"]["year"] == 1.0
    assert "2025 -> Cadeautjes" in split["detail"]


def test_no_split_is_claimed_when_nothing_separates_the_rows():
    rows = [(tx(f"0{d}-03-2024", "10.00", rem="same text"), c)
            for d, c in zip((4, 5, 6, 7, 8, 4), ("Huishouden", "Cadeautjes") * 3)]
    split = rc.best_split(rows)
    assert split["best"] is None


def test_a_split_that_fits_only_its_own_rows_loses_leave_one_out():
    """One keyword per row fits perfectly in-sample and predicts nothing."""
    rows = [(tx(f"0{d}-03-2024", "10.00", rem=w), c) for d, w, c in (
        (4, "alpha", "Huishouden"), (5, "bravo", "Cadeautjes"), (6, "charlie", "Huishouden"),
        (7, "delta", "Cadeautjes"), (8, "echo", "Huishouden"), (4, "foxtrot", "Cadeautjes"))]
    assert rc.best_split(rows)["best"] is None


# ── linking pot transfers to the purchases they cover ──────────────────────

def test_subsets_summing_finds_exact_sums_up_to_four_items():
    values = {0: 1, 1: 100, 2: 2, 3: 3, 4: 4}
    assert rc.subsets_summing(values, 10, 4, limit=5) == [frozenset({0, 2, 3, 4})]
    values = {0: 10, 1: 20, 2: 15, 3: 15, 4: 5}
    assert len(rc.subsets_summing(values, 30, 4, limit=10)) == 4
    assert len(rc.subsets_summing(values, 30, 4, limit=2)) == 2


def test_savings_accounts_are_found_from_labelled_incoming_rows():
    pairs = ([(tx("01-03-2024", "10.00", out=False, iban=SAVINGS), "Spaarrekening")] * 3 +
             [(tx("01-03-2024", "10.00", out=False, iban=PERSONAL), "Gift")] * 3)
    assert rc.savings_accounts(pairs) == {SAVINGS}


def links(txs, truths, window=7):
    truth_of = {id(t): c for t, c in zip(txs, truths) if c}
    return rc.find_links(txs, truth_of, {SAVINGS}, window, 4)


def cover(date, amount):
    return tx(date, amount, name="Spaarrekening", out=False, iban=SAVINGS)


def test_one_transfer_covering_one_purchase_is_linked():
    got = links([cover("11-03-2024", "45.00"), tx("09-03-2024", "45.00")], ["Spaarrekening", "Uit spaarpotje"])
    assert (got["covers"], got["linked"], got["explained"], got["targets"]) == (1, 1, 1, 1)


def test_one_transfer_covering_several_purchases_links_them_all():
    got = links([cover("20-03-2024", "30.00"), tx("18-03-2024", "10.00"), tx("19-03-2024", "20.00"),
                 tx("19-03-2024", "7.77")],
                ["Spaarrekening", "Uit spaarpotje", "Uit spaarpotje", "Boodschappen"])
    assert got["linked"] == 1 and got["explained"] == 2 and not got["claimed_other"]


def test_a_set_larger_than_allowed_is_not_linked():
    txs = [cover("20-03-2024", "30.00"), tx("18-03-2024", "10.00"), tx("19-03-2024", "20.00")]
    truth_of = {id(t): "Uit spaarpotje" for t in txs[1:]}
    assert rc.find_links(txs, truth_of, {SAVINGS}, 7, 1)["none"] == 1
    assert rc.find_links(txs, truth_of, {SAVINGS}, 7, 2)["explained"] == 2


def test_two_ways_to_make_the_sum_link_nothing():
    got = links([cover("20-03-2024", "30.00"), tx("18-03-2024", "10.00"), tx("18-03-2024", "20.00"),
                 tx("19-03-2024", "15.00"), tx("19-03-2024", "15.00", seq="2")],
                ["Spaarrekening", "Uit spaarpotje", "Uit spaarpotje", "Boodschappen", "Boodschappen"])
    assert got["ambiguous"] == 1 and got["explained"] == 0 and not got["claimed_other"]


def test_the_window_limits_how_far_a_purchase_may_be():
    txs = [cover("31-03-2024", "50.00"), tx("10-03-2024", "50.00")]
    truths = ["Spaarrekening", "Uit spaarpotje"]
    assert links(txs, truths, window=7)["none"] == 1
    assert links(txs, truths, window=31)["explained"] == 1


def test_a_wrong_claim_is_counted_by_its_true_category():
    got = links([cover("11-03-2024", "12.34"), tx("10-03-2024", "12.34")], ["Spaarrekening", "Boodschappen"])
    assert got["claimed_other"] == {"Boodschappen": 1}


def test_money_moved_into_the_savings_account_is_no_purchase():
    got = links([cover("11-03-2024", "45.00"), tx("11-03-2024", "45.00", iban=SAVINGS)],
                ["Spaarrekening", "Naar spaarpotjes"])
    assert got["none"] == 1


def test_a_purchase_two_transfers_both_claim_is_linked_to_neither():
    got = links([cover("01-03-2024", "25.00"), cover("03-03-2024", "25.00"), tx("02-03-2024", "25.00")],
                ["Spaarrekening", "Spaarrekening", "Uit spaarpotje"])
    assert got["conflict"] == 2 and got["explained"] == 0


# ── the whole analysis: years, stability, the draft ─────────────────────────

def row(t, category):
    d, m, y = t["booking_date"].split("-")
    block = "income" if t["credit_debit_indicator"] == "CRDT" else "expenses"
    amount = t["transaction_amount"]["amount"].lstrip("-")
    return ev.SheetRow(f"{m}/{y}", block, f"{y}-{m}-{d}", amount, category, False)


DATA = [
    (tx("04-03-2024", "11.00", name="JUMBO UTRECHT"), "Boodschappen"),
    (tx("04-03-2025", "12.00", name="JUMBO UTRECHT"), "Cadeautjes"),
    (tx("05-03-2024", "4.10", name="Bakker Bart 12 Driebergen"), "Boodschappen"),
    (tx("06-03-2024", "4.20", name="Bakker Bart 12 Driebergen"), "Boodschappen"),
    (tx("07-03-2024", "4.30", name="BAKKER BART"), "Boodschappen"),
    (tx("08-03-2024", "4.40", name="Bakker Bartholomeus"), "Huishouden"),
    (tx("11-03-2024", "4.50", name="Tikkie", rem="voor bakker bart"), "Boodschappen"),
    (tx("12-03-2024", "25.00", name="Oma Jansen", out=False), "Gift"),
    (tx("13-03-2024", "26.00", name="Oma Jansen", out=False), "Gift"),
    (tx("14-03-2024", "27.00", name="Oma Jansen", out=False), "Gift"),
    (tx("04-03-2024", "3.10", name="Hema"), "Huishouden"),
    (tx("05-03-2024", "3.20", name="Hema"), "Huishouden"),
    (tx("04-03-2025", "3.30", name="Hema"), "Cadeautjes"),
    (tx("05-03-2025", "3.40", name="Hema"), "Cadeautjes"),
    (tx("01-03-2024", "150.00", name="Me", iban=PERSONAL), "Persoonlijk vrij geld"),
    (tx("01-04-2024", "150.00", name="Me", iban=PERSONAL), "Persoonlijk vrij geld"),
    (cover("15-03-2024", "45.00"), "Spaarrekening"),
    (cover("16-03-2024", "46.00"), "Spaarrekening"),
    (cover("17-03-2024", "47.00"), "Spaarrekening"),
    (tx("14-03-2024", "45.00", name="Webshop"), "Uit spaarpotje"),
    # 80 % Boodschappen overall, but 2025 is all Snacken: no draft rule.
    *[(tx(f"1{d}-04-2024", f"6.{d}0", name="Kiosk"), "Boodschappen") for d in range(8)],
    (tx("10-04-2025", "7.10", name="Kiosk"), "Snacken"),
    (tx("11-04-2025", "7.20", name="Kiosk"), "Snacken"),
    # A church with a shop: donations by iDEAL, one card payment in the shop.
    (tx("02-05-2024", "20.00", name="Kerk De Rots", code="1 IDE"), "Goeie doelen"),
    (tx("09-05-2024", "25.00", name="Kerk De Rots", code="1 IDE"), "Goeie doelen"),
    (tx("16-05-2024", "8.50", name="Kerk De Rots", code="1 BEA"), "Boodschappen"),
    # Hyphen and accent in the name: the pattern must still match its own rows.
    (tx("03-05-2024", "9.10", name="Café-Zon B.V."), "Dates/uitjes"),
    (tx("10-05-2024", "9.20", name="Café-Zon B.V."), "Dates/uitjes"),
    (tx("17-05-2024", "9.30", name="CAFÉ ZON"), "Dates/uitjes"),
]


def coverage():
    txs = [t for t, _ in DATA]
    m = ev.match_rows(txs, [row(t, c) for t, c in DATA], VALID, {})
    return rc.rule_coverage(m.records, m.truths, txs, spaarpot_names=[])


def test_rule_precision_is_split_per_year():
    (pattern,) = [p for p in coverage()["rules"] if "JUMBO" in p]
    assert coverage()["rules"][pattern]["years"] == {"2024": [1, 1], "2025": [1, 0]}


def test_a_group_whose_category_changes_between_years_shifts():
    groups = {g["key"]: g for g in coverage()["name_groups"]}
    assert groups["hema"]["stability"] == "shifts"
    assert groups["bakker bart"]["stability"] == "one year"


def test_mixed_groups_carry_a_split_and_pure_ones_do_not():
    groups = {g["key"]: g for g in coverage()["name_groups"]}
    assert "split" in groups["hema"] and "split" not in groups["bakker bart"]


def decisions():
    return {d["key"]: d for d in coverage()["draft"]}


def test_a_uniform_group_is_proposed_as_a_plain_rule_with_word_bounds():
    bakker = decisions()["bakker bart"]
    assert bakker["decision"] == "keep"
    assert bakker["pattern"] == r"\bbakker\W+bart\b"
    assert bakker["member"] == "ExpenseCategory.BOODSCHAPPEN"
    # Over every uncovered row: the Tikkie row matches too, Bartholomeus not.
    assert (bakker["hits"], bakker["correct"]) == (4, 4)
    assert decisions()["oma jansen"]["member"] == "IncomeCategory.GIFT"


def test_a_pattern_matches_its_own_rows_despite_hyphens_and_accents():
    cafe = decisions()["café zon"]
    assert (cafe["hits"], cafe["correct"]) == (3, 3)


def test_a_mixed_group_is_proposed_for_review_under_its_top_category():
    """Kruidvat-like shops: most common category, always marked for review."""
    hema = decisions()["hema"]
    assert hema["decision"] == "review"


def test_a_group_that_shifted_follows_its_latest_year():
    kiosk = decisions()["kiosk"]
    assert kiosk["decision"] == "review" and kiosk["category"] == "Snacken"


def test_a_group_a_quarter_donations_is_proposed_as_goeie_doelen():
    """Missing a donation costs a tax deduction; a wrong one is filtered by hand."""
    kerk = decisions()["kerk de"]
    assert kerk["decision"] == "gd" and kerk["category"] == "Goeie doelen"


def test_goeie_doelen_recall_is_reported():
    watch = coverage()["watch"]
    assert watch["total"] == 2 and watch["by_rules"] == 0 and watch["by_decisions"] == 2
    assert watch["marked_other"] == 1


def test_the_report_includes_links_for_each_window_and_set_size():
    """Larger windows and sets explain more but also match more by chance."""
    cov = coverage()
    assert set(cov["links"]) == {(w, k) for w in rc.LINK_WINDOWS for k in range(1, rc.LINK_MAX_ITEMS + 1)}
    assert cov["links"][(7, 1)]["explained"] == 1


def test_account_roles_are_suggested_from_savings_and_free_money_rows():
    roles = coverage()["accounts"]
    assert roles[SAVINGS]["role"] == "savings" and roles[PERSONAL]["role"] == "personal"


def test_printed_report_holds_no_keywords_thresholds_names_or_ibans():
    out = "\n".join(rc.format_rule_coverage(coverage()))
    assert "best split" in out and "decisions proposed" in out and "links" in out
    assert "Goeie doelen recall" in out
    assert "time of day" in out and "2024" in out
    for secret in (SAVINGS, PERSONAL, "bakker", "Bakker", "hema", "Hema", "Oma", "Jansen",
                   "Webshop", "Tikkie", "Kerk", "Rots", "Café", "45.00", "150.00", "3.25", r"\b"):
        assert secret not in out


def test_the_draft_file_is_a_private_decision_table(tmp_path):
    path = tmp_path / "draft.txt"
    rc.write_draft(coverage(), str(path))
    lines = path.read_text().splitlines()
    bakker = next(line for line in lines if "\tbakker bart\t" in line)
    assert bakker.split("\t")[:4] == ["keep", bakker.split("\t")[1], "out", "Boodschappen"]
    assert r"\bbakker\W+bart\b" in bakker
    assert any(line.startswith("gd\t") and "\tkerk de\t" in line for line in lines)
    assert any(line.startswith("review\t") and "\thema\t" in line for line in lines)
    text = "\n".join(lines)
    assert SAVINGS in text and PERSONAL in text
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_an_amount_cut_that_only_fits_noise_is_not_claimed():
    """In-sample, a cut after the first row scores 4/6 against a 3/6 majority."""
    rows = [(tx(f"0{d}-03-2024", f"{d}.00"), c)
            for d, c in zip((4, 5, 6, 7, 8, 9), ("Huishouden", "Cadeautjes") * 3)]
    assert rc.best_split(rows)["best"] is None
