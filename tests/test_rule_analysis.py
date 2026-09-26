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
    # 80 % Boodschappen overall, but 2025 is all Snacken, and nothing but
    # the year tells them apart (amounts interleave): review, no split.
    *[(tx(f"1{d}-04-2024", f"6.{d}0", name="Kiosk"), "Boodschappen") for d in range(8)],
    (tx("10-04-2025", "6.05", name="Kiosk"), "Snacken"),
    (tx("11-04-2025", "6.45", name="Kiosk"), "Snacken"),
    # A church with a shop: donations by iDEAL, one card payment in the shop.
    (tx("02-05-2024", "20.00", name="Kerk De Rots", code="1 IDE"), "Goeie doelen"),
    (tx("09-05-2024", "25.00", name="Kerk De Rots", code="1 IDE"), "Goeie doelen"),
    (tx("16-05-2024", "8.50", name="Kerk De Rots", code="1 BEA"), "Boodschappen"),
    # Hyphen and accent in the name: the pattern must still match its own rows.
    (tx("03-05-2024", "9.10", name="Café-Zon B.V."), "Dates/uitjes"),
    (tx("10-05-2024", "9.20", name="Café-Zon B.V."), "Dates/uitjes"),
    (tx("17-05-2024", "9.30", name="CAFÉ ZON"), "Dates/uitjes"),
]


def coverage(data=DATA, since=None):
    txs = [t for t, _ in data]
    m = ev.match_rows(txs, [row(t, c) for t, c in data], VALID, {})
    return rc.rule_coverage(m.records, m.truths, txs, spaarpot_names=[], since=since)


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
    assert bakker["pattern"] == r"\bbakker" + rc.KEY_GAP + r"bart\b"
    assert bakker["member"] == "ExpenseCategory.BOODSCHAPPEN"
    # Over every uncovered row: the Tikkie row matches too, Bartholomeus not.
    assert (bakker["hits"], bakker["correct"]) == (4, 4)
    assert decisions()["oma jansen"]["member"] == "IncomeCategory.GIFT"


def test_a_pattern_matches_its_own_rows_despite_hyphens_and_accents():
    cafe = decisions()["café zon"]
    assert (cafe["hits"], cafe["correct"]) == (3, 3)


def test_a_mixed_group_below_the_review_share_goes_to_the_ai():
    """Marking rows whose top category is right half the time costs more than the AI."""
    hema = decisions()["hema"]
    assert (hema["decision"], hema["why"]) == ("drop", "mixed")


def test_a_pattern_skips_an_initial_the_key_left_out():
    """The key drops one-letter words, so the pattern must step over them."""
    data = [(tx(f"0{d}-03-2025", f"{d}.00", name=n), "Persoonlijk vrij geld")
            for d, n in ((4, "Jan P Bakker"), (5, "JAN P. BAKKER"), (6, "Jan_Bakker"))]
    (draft,) = coverage(data)["draft"]
    assert draft["key"] == "jan bakker" and (draft["hits"], draft["correct"]) == (3, 3)


def test_a_group_that_shifted_follows_its_latest_year():
    kiosk = decisions()["kiosk"]
    assert kiosk["decision"] == "review" and kiosk["category"] == "Snacken"


def test_a_year_split_is_never_proposed_as_a_rule():
    """A future row is always in a new year, so `2025 -> X` cannot repeat."""
    groups = {g["key"]: g for g in coverage()["name_groups"]}
    assert groups["kiosk"]["split"]["best"] == "year"
    assert decisions()["kiosk"]["split"] is None


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
    assert r"\bbakker" + rc.KEY_GAP + r"bart\b" in bakker
    assert any(line.startswith("gd\t") and "\tkerk de\t" in line for line in lines)
    assert any(line.startswith("drop\t") and "\thema\t" in line for line in lines)
    assert any(line.startswith("review\t") and "\tkiosk\t" in line for line in lines)
    text = "\n".join(lines)
    assert SAVINGS in text and PERSONAL in text
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_an_amount_cut_that_only_fits_noise_is_not_claimed():
    """In-sample, a cut after the first row scores 4/6 against a 3/6 majority."""
    rows = [(tx(f"0{d}-03-2024", f"{d}.00"), c)
            for d, c in zip((4, 5, 6, 7, 8, 9), ("Huishouden", "Cadeautjes") * 3)]
    assert rc.best_split(rows)["best"] is None


# ── proposals from the last 12 months ──────────────────────────────────────

def _monthly(day, amount, name, category, months=range(1, 13), year=2025, **kw):
    return [(tx(f"{day:02d}-{m:02d}-{year}", amount, name=name, **kw), category) for m in months]


RECENT = [
    # Fixed monthly free money to a personal account, next to wrong-card
    # repayments to the same account: the recurring amount separates them,
    # and a repayment takes the category of what was bought (the AI).
    *_monthly(1, "150.00", "Eigen Rekening", "Persoonlijk vrij geld", iban=PERSONAL),
    (tx("14-02-2025", "12.34", name="Eigen Rekening", iban=PERSONAL), "Boodschappen"),
    (tx("15-04-2025", "23.45", name="Eigen Rekening", iban=PERSONAL), "Boodschappen"),
    (tx("16-06-2025", "34.56", name="Eigen Rekening", iban=PERSONAL), "Huishouden"),
    (tx("15-08-2025", "45.67", name="Eigen Rekening", iban=PERSONAL), "Cadeautjes"),
    # Huishouden before the move, Boodschappen since: the recent rows decide.
    *[(tx(f"10-0{m}-2024", f"{m}.10", name="Buurtwinkel"), "Huishouden") for m in range(1, 6)],
    *[(tx(f"1{m}-03-2025", f"{m}.20", name="Buurtwinkel"), "Boodschappen") for m in range(0, 4)],
    # Only before the move.
    *_monthly(20, "5.00", "Oude Slager", "Boodschappen", months=(2, 3, 4), year=2024),
    # Mostly before the move, once since.
    *_monthly(21, "6.00", "Verhuisd Bakkerij", "Boodschappen", months=(1, 2, 3, 4), year=2024),
    (tx("21-01-2025", "6.00", name="Verhuisd Bakkerij"), "Boodschappen"),
    # Card payments at the bar, subscription by iDEAL: the code separates them.
    *[(tx(f"0{d}-03-2025", a, name="Sportschool", code="1 BEA"), "Dates/uitjes")
      for d, a in zip((3, 4, 5, 6), ("10.00", "30.00", "10.00", "30.00"))],
    *[(tx(f"1{d}-03-2025", a, name="Sportschool", code="1 IDE"), "Rekeningen")
      for d, a in zip((0, 1, 2, 3), ("20.00", "40.00", "20.00", "40.00"))],
    # A multi-purpose shop: nothing separates the rows.
    *[(tx(f"{d:02d}-05-2025", "10.00", name="Warenhuis", rem="x"), c)
      for d, c in zip((5, 6, 7, 8, 9, 12), ("Huishouden", "Cadeautjes") * 3)],
    # The code splits it, but leaves both branches mixed: still review.
    *[(tx(f"{d:02d}-07-2025", "10.00", name="Tweeluik", code="1 BEA"), c)
      for d, c in zip((7, 8, 9, 10, 11), ("Huishouden",) * 4 + ("Cadeautjes",))],
    *[(tx(f"{d:02d}-07-2025", "10.00", name="Tweeluik", code="1 IDE"), c)
      for d, c in zip((14, 15, 16, 17, 18), ("Cadeautjes",) * 4 + ("Huishouden",))],
    # A multi-purpose shop at 80 %: marked under its top category.
    *[(tx(f"{d:02d}-09-2025", "10.00", name="Tuincentrum", rem="x"), c)
      for d, c in zip((1, 2, 3, 4, 5), ("Huishouden",) * 4 + ("Cadeautjes",))],
    # Donations by iDEAL, one card payment in the church shop.
    (tx("02-06-2025", "20.00", name="Kerk Het Licht", code="1 IDE"), "Goeie doelen"),
    (tx("09-06-2025", "25.00", name="Kerk Het Licht", code="1 IDE"), "Goeie doelen"),
    (tx("16-06-2025", "8.50", name="Kerk Het Licht", code="1 BEA"), "Boodschappen"),
    # Covered by today's rules, once wrongly.
    (tx("20-06-2025", "11.00", name="JUMBO UTRECHT"), "Boodschappen"),
    (tx("23-06-2025", "12.00", name="JUMBO UTRECHT"), "Cadeautjes"),
]


def recent():
    return {d["key"]: d for d in coverage(RECENT)["draft"]}


def test_the_window_is_the_last_twelve_sheet_months_in_the_data():
    assert coverage(RECENT)["window"] == [f"{m:02d}/2025" for m in range(1, 13)]


def test_a_group_is_judged_on_its_recent_rows_only():
    shop = recent()["buurtwinkel"]
    assert shop["decision"] == "keep" and shop["category"] == "Boodschappen"
    assert (shop["recent"], shop["rows"]) == (4, 9)
    # What it would write is counted over the window too: not the old rows.
    assert (shop["hits"], shop["correct"]) == (4, 4)


def test_a_group_not_seen_in_twelve_months_is_dropped():
    old = recent()["oude slager"]
    assert (old["decision"], old["why"]) == ("drop", "not seen")


def test_a_group_with_too_few_recent_rows_is_dropped():
    moved = recent()["verhuisd bakkerij"]
    assert (moved["decision"], moved["why"]) == ("drop", "too few")


def test_the_recurring_amount_splits_free_money_from_repayments():
    own = recent()["eigen rekening"]
    assert own["decision"] == "split" and own["split"]["feature"] == "recurring amount"
    # The mixed branch goes to the AI; only the fixed amount gets a category.
    assert sorted(own["split"]["outcomes"]) == ["Persoonlijk vrij geld", "ai"]
    assert (own["hits"], own["correct"]) == (12, 12)


def test_the_transaction_code_splits_a_group_into_two_categories():
    gym = recent()["sportschool"]
    assert gym["decision"] == "split" and gym["split"]["feature"] == "code"
    assert sorted(gym["split"]["outcomes"]) == ["Dates/uitjes", "Rekeningen"]
    assert (gym["hits"], gym["correct"]) == (8, 8)


def test_a_group_nothing_separates_is_marked_from_the_review_share():
    """Kruidvat-like shops: most common category, always marked for review."""
    assert rc.REVIEW_SHARE == 0.8
    shop = recent()["tuincentrum"]
    assert (shop["decision"], shop["category"], shop["split"]) == ("review", "Huishouden", None)


def test_a_group_nothing_separates_below_the_review_share_is_dropped():
    assert (recent()["warenhuis"]["decision"], recent()["warenhuis"]["why"]) == ("drop", "mixed")


def test_a_split_that_leaves_every_branch_mixed_is_not_a_split():
    assert recent()["tweeluik"]["decision"] == "drop"


def test_the_projection_counts_what_would_still_need_the_user():
    """Over the window: today's rules, the proposals, and what the AI gets."""
    p = coverage(RECENT)["projection"]
    assert p["months"] == 12
    assert p["today"] == dict(rules=2, rules_wrong=1, plain=0, plain_wrong=0, marked=0, ai=53)
    # Plain: 12 free money, 4 Buurtwinkel, 8 Sportschool, 2 donations.
    # Marked: 5 Tuincentrum, the card payment at the church.
    # AI: 4 repayments, the one recent Verhuisd Bakkerij row, 6 Warenhuis, 10 Tweeluik.
    assert p["proposed"] == dict(rules=2, rules_wrong=1, plain=26, plain_wrong=0, marked=6, ai=21)


def test_the_projection_is_printed_per_month_with_the_ai_estimate():
    out = "\n".join(rc.format_rule_coverage(coverage(RECENT)))
    need_today = 53 * rc.AI_FLAG_RATE / 12
    need_proposed = (6 + 21 * rc.AI_FLAG_RATE) / 12
    assert f"today: {need_today:.1f} rows need you" in out
    assert f"proposed: {need_proposed:.1f} rows need you" in out


def test_the_printed_splits_name_the_feature_but_not_the_amount_or_the_word():
    out = "\n".join(rc.format_rule_coverage(coverage(RECENT)))
    assert "split by recurring amount" in out and "split by code" in out
    assert "drop" in out and "not seen in the window" in out
    for secret in (PERSONAL, "150.00", "Eigen", "eigen", "Sportschool", "Warenhuis", "Buurtwinkel"):
        assert secret not in out


def test_the_draft_file_holds_each_split_with_its_branches(tmp_path):
    path = tmp_path / "draft.txt"
    rc.write_draft(coverage(RECENT), str(path))
    lines = path.read_text().splitlines()
    own = next(line for line in lines if "\teigen rekening\t" in line)
    assert own.startswith("split\t")
    assert "at 150.00 -> Persoonlijk vrij geld" in own and "not at 150.00 -> ai" in own
    assert next(line for line in lines if "\toude slager\t" in line).startswith("drop\t")


def test_the_window_can_start_at_a_given_sheet_month():
    """After the move: only months from the given one count."""
    cov = coverage(RECENT, since="06/2025")
    assert cov["window"] == [f"{m:02d}/2025" for m in range(6, 13)]
    assert (cov["projection"]["months"], recent_since("06/2025")["buurtwinkel"]["why"]) == (7, "not seen")


def recent_since(since):
    return {d["key"]: d for d in coverage(RECENT, since=since)["draft"]}


def test_a_changed_fixed_amount_still_counts_as_recurring():
    """Free money went up once: both amounts recur, the repayments do not."""
    data = ([(tx(f"01-{m:02d}-2025", "100.00" if m < 7 else "125.00", name="Eigen Rekening"),
              "Persoonlijk vrij geld") for m in range(1, 13)] +
            [(tx(f"15-{m:02d}-2025", a, name="Eigen Rekening"), c) for m, a, c in (
                (2, "12.34", "Boodschappen"), (4, "23.45", "Boodschappen"),
                (6, "34.56", "Huishouden"), (8, "45.67", "Cadeautjes"))])
    (own,) = coverage(data)["draft"]
    assert own["decision"] == "split" and own["split"]["feature"] == "recurring amount"
    # Only the most repeated amount would catch 6 of the 12.
    assert (own["hits"], own["correct"]) == (12, 12)
