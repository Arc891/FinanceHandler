"""
Tests for the production rules of Phase 4's rule work (step 2): what a rule
may check beyond its pattern (account role, direction, code, amount, time of
day, weekday, a word), the local rules file the user's decisions become
(src/config/local_rules.tsv, git-ignored), the order the rules run in
(account rules, then constants.py, then the local file), and the two rule
fixes in constants.py. All rows and account numbers are synthetic.
"""

import pytest

from constants import ExpenseCategory, IncomeCategory
from finance_core import categorization_rules as cr
from finance_core import local_rules as lr
from finance_core.rule_conditions import parse_when
from finance_core.tx_features import account_role
from fakes import expense_tx, income_tx

SAVINGS = "NL99SAVE0000000001"
HERS = "NL98HERS0000000002"
MINE = "NL97MINE0000000003"
ROLES = {"savings": [SAVINGS], "partner_personal": ["nl98 hers 0000 0000 02"], "user_personal": [MINE]}


@pytest.fixture(autouse=True)
def roles(monkeypatch):
    monkeypatch.setattr("finance_core.tx_features.account_roles", lambda: ROLES)


def tx(date="04-03-2025", amount="10.00", name="Shop", rem="", out=True, iban="", code="8810 BEA"):
    make = expense_tx if out else income_tx
    t = make(date_str=date, amount=f"-{amount}" if out else amount, name=name, rem=rem)
    t = {k: v for k, v in t.items() if k not in ("description", "category")}
    t["counterparty_iban"] = iban
    t["bank_transaction_code"] = {"description": code}
    return t


def rules(*lines):
    return lr.parse_local_rules("\n".join("\t".join(line) for line in lines))


# ── conditions ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("when, row, expected", [
    ("-", tx(), True),
    ("code=BEA", tx(code="1 BEA"), True),
    ("code=BEA", tx(code="1 IDE"), False),
    ("code!=BEA", tx(code="1 IDE"), True),
    ("amount>=100", tx(amount="100.00"), True),
    ("amount>=100", tx(amount="99.99"), False),
    ("amount<12.50", tx(amount="12.49"), True),
    ("amount=100.00/125.00", tx(amount="125.00"), True),
    ("amount=100.00/125.00", tx(amount="125.01"), False),
    ("amount!=100.00/125.00", tx(amount="12.34"), True),
    ("hour<12.5", tx(rem="BEA 04.03.25/12:10 UTRECHT"), True),
    ("hour>=12.5", tx(rem="BEA 04.03.25/12:10 UTRECHT"), False),
    ("hour=none", tx(rem="factuur maart"), True),
    ("weekend", tx(date="08-03-2025"), True),
    ("weekday", tx(date="08-03-2025"), False),
    ("word=premie", tx(rem="Premie maart"), True),
    ("word!=premie", tx(rem="nota eigen risico"), True),
    ("role=savings", tx(iban=SAVINGS), True),
    ("role=partner_personal", tx(iban=HERS), True),
    ("role!=savings", tx(iban=MINE), True),
    ("role=savings", tx(iban=""), False),
    ("code=BEA amount<20", tx(amount="15.00"), True),
    ("code=BEA amount<20", tx(amount="25.00"), False),
])
def test_a_condition_checks_one_feature_of_the_row(when, row, expected):
    assert parse_when(when)(row) is expected


@pytest.mark.parametrize("when", ["amount>=", "amount>=abc", "colour=red", "hour<x", "role=",
                                  "code=bea", "amount=1/x", "weekends"])
def test_a_malformed_condition_is_refused(when):
    with pytest.raises(ValueError):
        parse_when(when)


def test_account_roles_match_ibans_whatever_their_spacing_or_case():
    assert account_role(tx(iban="NL98HERS0000000002")) == "partner_personal"
    assert account_role(tx(iban="nl97mine0000000003")) == "user_personal"
    assert account_role(tx(iban="NL00OTHR0000000000")) is None


# ── the local rules file ────────────────────────────────────────────────────

def test_a_rules_file_line_becomes_a_rule():
    (rule,) = rules(("out", r"\bbakker\W+bart\b", "-", "Boodschappen", "-", "Bakker Bart", "N03"))
    assert (rule.direction, rule.category, rule.marked, rule.description) == (
        "out", ExpenseCategory.BOODSCHAPPEN, False, "Bakker Bart")


def test_comments_and_blank_lines_are_skipped():
    assert rules(("# a comment",), ("",), ("out", "x", "-", "Boodschappen", "?", "X")) != []


@pytest.mark.parametrize("line, problem", [
    (("sideways", "x", "-", "Boodschappen", "-", "X"), "direction"),
    (("out", "(unclosed", "-", "Boodschappen", "-", "X"), "pattern"),
    (("out", "x", "colour=red", "Boodschappen", "-", "X"), "condition"),
    (("out", "x", "-", "Salaris", "-", "X"), "category"),          # an income category on an expense
    (("in", "x", "-", "Goeie doelen", "-", "X"), "category"),
    (("out", "x", "-", "Boodschappen", "!", "X"), "mark"),
    (("out", "x", "-", "Boodschappen", "-", "-"), "description"),
    (("out", "x", "-", "Boodschappen"), "columns"),
])
def test_a_bad_line_is_refused_with_its_line_number_but_not_its_text(line, problem):
    with pytest.raises(lr.LocalRulesError) as err:
        rules(("# header",), line)
    message = str(err.value)
    assert "line 2" in message and problem in message
    assert "(unclosed" not in message and "colour" not in message


def test_a_missing_rules_file_means_no_local_rules(tmp_path):
    assert lr.load_local_rules(tmp_path / "absent.tsv") == []


def test_the_rules_file_is_read_again_when_it_changes(tmp_path, monkeypatch):
    path = tmp_path / "local_rules.tsv"
    monkeypatch.setattr(lr, "setting", lambda name, default=None: str(path))
    path.write_text("out\tx\t-\tBoodschappen\t-\tX\n")
    assert len(lr.default_local_rules()) == 1
    path.write_text("out\tx\t-\tBoodschappen\t-\tX\nout\ty\t-\tHuishouden\t-\tY\n")
    import os
    os.utime(path, (1, 1))
    assert len(lr.default_local_rules()) == 2


# ── matching, and the order rules run in ────────────────────────────────────

def test_a_local_rule_writes_its_description_and_category():
    local = rules(("out", r"\bbakker\W+bart\b", "-", "Boodschappen", "-", "Bakker Bart"))
    assert cr.rule_result(tx(name="Bakker Bart 12"), local) == ("Boodschappen", "Bakker Bart", False)


def test_a_marked_rule_says_so():
    local = rules(("out", "kruidvat", "-", "Persoonlijke verzorging", "?", "Kruidvat"))
    assert cr.rule_result(tx(name="KRUIDVAT 7"), local) == ("Persoonlijke verzorging", "Kruidvat", True)


def test_the_first_local_rule_whose_pattern_and_condition_hold_wins():
    local = rules(("out", "eigen", "amount>=100", "Persoonlijk vrij geld", "-", "Eigen Rekening"),
                  ("out", "eigen", "-", "ai", "-", "-"),
                  ("out", "eigen", "-", "Boodschappen", "-", "Never reached"))
    assert cr.rule_result(tx(name="Eigen", amount="150.00"), local)[0] == "Persoonlijk vrij geld"
    # `ai` stops the local rules: the row goes to the AI.
    assert cr.rule_result(tx(name="Eigen", amount="12.34"), local) is None


def test_a_local_rule_fires_for_its_own_direction_only():
    local = rules(("out", "oma", "-", "Cadeautjes", "-", "Oma"))
    assert cr.rule_result(tx(name="Oma", out=False), local) is None


def test_the_rules_in_constants_run_before_the_local_rules():
    """Local rules were measured on the rows today's rules leave uncovered."""
    local = rules(("out", "picnic", "-", "Cadeautjes", "-", "Picnic cadeau"))
    assert cr.rule_result(tx(name="PICNIC"), local)[0] == "Boodschappen"


def test_salaris_from_her_account_is_gemeente():
    """She passes on her Gemeente money with the word "salaris"; the sender decides."""
    got = cr.rule_result(tx(name="Her", rem="salaris", out=False, iban=HERS), [])
    assert got == ("Gemeente", "Gemeente uitkering", False)


def test_salaris_from_any_other_account_stays_salaris():
    assert cr.rule_result(tx(name="Werkgever", rem="SALARIS", out=False, iban=MINE), [])[0] == "Salaris"
    assert cr.rule_result(tx(name="Werkgever", rem="SALARIS", out=False), [])[0] == "Salaris"


def test_the_snackbar_is_dinner():
    assert cr.rule_result(tx(name="Snackbar Traay"), [])[0] == ExpenseCategory.BOODSCHAPPEN.value


def test_the_old_two_value_helper_still_answers():
    assert cr.apply_categorization_rules(tx(name="PICNIC")) == ("Boodschappen", "Picnic inkopen")


def test_without_a_config_no_account_is_known(monkeypatch):
    monkeypatch.setattr("finance_core.tx_features.account_roles", lambda: {})
    assert account_role(tx(iban=SAVINGS)) is None
    assert IncomeCategory.GEMEENTE.value == "Gemeente"
