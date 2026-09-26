"""
Tests for eval_categoriser --rules: where more regex rules would help.

The report runs the regex pass only (no AI) over the hand-checked months and
prints per-rule precision, the rows no rule covers, counterparty groups among
those rows (by name and by IBAN), and rows that have a mirror: an opposite
row of the same amount within a week. It prints counts, category names, rule
patterns (which are code) and anonymous group ids only; names and IBANs go
to the --names-out file, which only the user reads. All data is synthetic.
"""

import os
import stat

import eval_categoriser as ev
from fakes import expense_tx, income_tx

VALID = {"expenses": {"Boodschappen", "Cadeautjes", "Huishouden", "Uit spaarpotje"},
         "income": {"Spaarrekening", "Gift"}}
SECRET_NAME = "Jolanda Vermeulen"
SECRET_IBAN = "NL99SAVE0000000001"


def raw(tx, iban=""):
    tx = {k: v for k, v in tx.items() if k not in ("description", "category")}
    tx["counterparty_iban"] = iban
    return tx


def expense(date, amount, name, rem="", seq="1", iban=""):
    return raw(expense_tx(date_str=date, amount=f"-{amount}", name=name, rem=rem, seq=seq), iban)


def income(date, amount, name, rem="", seq="1", iban=""):
    return raw(income_tx(date_str=date, amount=amount, name=name, rem=rem, seq=seq), iban)


def row(date, amount, category, block="expenses"):
    d, m, y = date.split("-")
    return ev.SheetRow(f"{m}/{y}", block, f"{y}-{m}-{d}", amount, category, False)


# (tx, sheet row or None when the tx is only a mirror, never scored)
DATA = [
    (expense("17-03-2024", "10.00", "JUMBO UTRECHT"), row("17-03-2024", "10.00", "Boodschappen")),
    (expense("18-03-2024", "20.00", "JUMBO UTRECHT"), row("18-03-2024", "20.00", "Cadeautjes")),
    (expense("02-03-2024", "3.10", "Hema 1234 Utrecht"), row("02-03-2024", "3.10", "Huishouden")),
    (expense("03-03-2024", "3.20", "HEMA 5678 AMSTERDAM"), row("03-03-2024", "3.20", "Huishouden")),
    (expense("04-04-2024", "3.30", "hema"), row("04-04-2024", "3.30", "Cadeautjes")),
    (expense("05-03-2024", "4.10", "Bakker Bart 12 Driebergen"), row("05-03-2024", "4.10", "Boodschappen")),
    (expense("06-03-2024", "4.20", "Bakker Bart 12 Driebergen"), row("06-03-2024", "4.20", "Boodschappen")),
    (expense("07-03-2024", "4.30", "BAKKER BART"), row("07-03-2024", "4.30", "Boodschappen")),
    (income("08-03-2024", "50.00", SECRET_NAME, iban=SECRET_IBAN),
     row("08-03-2024", "50.00", "Spaarrekening", "income")),
    (income("09-03-2024", "60.00", "J. Vermeulen", iban=SECRET_IBAN),
     row("09-03-2024", "60.00", "Spaarrekening", "income")),
    (income("12-03-2024", "70.00", "Vermeulen J", iban=SECRET_IBAN),
     row("12-03-2024", "70.00", "Spaarrekening", "income")),
    # A purchase paid from a pot: the pot's transfer lands the next day.
    (expense("10-03-2024", "45.00", "Webshop"), row("10-03-2024", "45.00", "Uit spaarpotje")),
    (income("11-03-2024", "45.00", SECRET_NAME, rem="Overboeking - Vakantie"), None),
    # Not mirrors: same direction, and three weeks away.
    (expense("10-03-2024", "45.00", "Other shop"), None),
    (income("31-03-2024", "45.00", SECRET_NAME, rem="Overboeking - Vakantie"), None),
]


def coverage():
    txs = [tx for tx, _ in DATA]
    m = ev.match_rows(txs, [r for _, r in DATA if r], VALID, {})
    return ev.rule_coverage(m.records, m.truths, txs, spaarpot_names=["Vakantie"])


def group(groups, key):
    return next(g for g in groups if g["key"] == key)


# ── the parts of the report ─────────────────────────────────────────────────

def test_merchant_key_drops_branch_numbers_places_and_case():
    keys = {ev.merchant_key(expense("01-01-2024", "1.00", n))
            for n in ("Hema 1234 Utrecht", "HEMA 5678 AMSTERDAM", "hema")}
    assert keys == {"hema"}
    assert ev.merchant_key(expense("01-01-2024", "1.00", "Bakker Bart 12 Driebergen")) == "bakker bart"


def test_merchant_key_falls_back_to_the_remittance_when_there_is_no_name():
    assert ev.merchant_key(expense("01-01-2024", "1.00", "", rem="CCV*Kiosk 7 Station")) == "ccv kiosk"


def test_each_rule_reports_hits_correct_and_what_it_got_wrong():
    cov = coverage()
    (pattern,) = [p for p in cov["rules"] if "JUMBO" in p]
    hit = cov["rules"][pattern]
    assert (hit["hits"], hit["correct"]) == (2, 1)
    assert hit["wrong"] == {"Cadeautjes": 1}


def test_rows_no_rule_covers_are_counted_per_true_category():
    cov = coverage()
    assert cov["uncovered"] == {"Huishouden": 2, "Cadeautjes": 1, "Boodschappen": 3,
                                "Spaarrekening": 3, "Uit spaarpotje": 1}


def test_uncovered_rows_group_by_name_as_pure_or_mixed():
    groups = coverage()["name_groups"]
    hema = group(groups, "hema")
    assert hema["rows"] == 3 and hema["months"] == 2
    assert hema["truths"] == {"Huishouden": 2, "Cadeautjes": 1}
    assert not hema["pure"]
    assert group(groups, "bakker bart")["pure"]


def test_uncovered_rows_group_by_iban_across_differing_names():
    savings = group(coverage()["iban_groups"], SECRET_IBAN)
    assert savings["rows"] == 3 and savings["pure"]
    assert savings["truths"] == {"Spaarrekening": 3}


def test_groups_below_the_minimum_size_are_left_out():
    assert all(g["rows"] >= ev.GROUP_MIN for g in coverage()["name_groups"])
    assert "webshop" not in {g["key"] for g in coverage()["name_groups"]}


def test_a_mirror_is_an_opposite_row_of_the_same_amount_within_a_week():
    mirrors = coverage()["mirrors"]
    assert mirrors["Uit spaarpotje"] == {"rows": 1, "mirrored": 1, "same_day": 0, "spaarpot": 1}
    assert mirrors["Huishouden"] == {"rows": 2, "mirrored": 0, "same_day": 0, "spaarpot": 0}


# ── privacy ─────────────────────────────────────────────────────────────────

def test_the_printed_report_holds_no_names_ibans_amounts_or_dates():
    out = "\n".join(ev.format_rule_coverage(coverage()))
    assert "N01" in out and "I01" in out and "Uit spaarpotje" in out
    for secret in (SECRET_NAME, "Vermeulen", SECRET_IBAN, "hema", "HEMA", "bakker",
                   "Webshop", "Vakantie", "45.00", "4.10", "2024-03", "10-03"):
        assert secret not in out


def test_names_go_to_a_private_file(tmp_path):
    path = tmp_path / "names.tsv"
    ev.write_names(coverage(), str(path))
    text = path.read_text()
    assert "hema" in text and SECRET_IBAN in text and "N01\t" in text
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


# ── end to end ──────────────────────────────────────────────────────────────

class FakeGc:
    def __init__(self, blocks):
        self.blocks = blocks

    def list_spreadsheet_files(self):
        return [{"name": "Maandelijks Budget 03/2024", "id": "x"}]

    def open_by_key(self, key):
        blocks = self.blocks

        class Book:
            def values_batch_get(self, ranges, params=None):
                return {"valueRanges": [{"values": blocks["B1:E"]}, {"values": blocks["G1:J"]}]}
        return Book()


def test_rules_mode_sends_nothing_to_the_ai(monkeypatch, capsys, tmp_path):
    txs = [expense("17-03-2024", "10.00", "JUMBO UTRECHT"),
           expense("02-03-2024", "3.10", SECRET_NAME)]
    blocks = {"B1:E": [["Date"], [45368, 10.0, "d", "Boodschappen"],
                       [45353, 3.1, "d", "Huishouden"]], "G1:J": []}
    monkeypatch.setattr(ev, "load_exports", lambda paths: (txs, 0))
    monkeypatch.setattr(ev, "service_account_client", lambda p: FakeGc(blocks))
    monkeypatch.setattr(ev, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(ev, "spaarpot_names", lambda: [])

    import automation.ai_categorizer as ai

    class NoAI:
        def __init__(self, *a, **k):
            raise AssertionError("the AI must not be built in --rules mode")
    monkeypatch.setattr(ai, "ClaudeCategorizer", NoAI)
    names = tmp_path / "names.tsv"
    code = ev.main(["--rules", "--names-out", str(names), "x.csv"])
    out = capsys.readouterr().out
    assert code == 0
    assert "rule coverage" in out and "names written to" in out
    assert SECRET_NAME not in out and "3.10" not in out
    assert names.exists()
