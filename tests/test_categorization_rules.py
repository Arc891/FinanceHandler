"""
Tests for finance_core.categorization_rules, the regex pass moved out of
transaction_prompt.py (plan 4.8, Phase 3 step 1).

The rules must behave exactly as they did in the UI module, and the engine
must no longer depend on that module, which Phase 3 step 5 deletes. The
last tests pin the fact behind 4.3's seeding choice: no period marker
matches a description the rules write into a sheet. All rows are synthetic.
"""

import re
import sys

from constants import ExpenseCategory, IncomeCategory
from finance_core.categorization_engine import CategorizationEngine
from finance_core.categorization_rules import apply_categorization_rules, first_matching_rule

MARKERS = [r"\bDUO\b", r"Anamata"]


def expense(counterparty="", remittance=""):
    return {
        "credit_debit_indicator": "DBIT",
        "debtor": {"name": counterparty},
        "creditor": {"name": ""},
        "remittance_information": [remittance] if remittance else [],
    }


def income(counterparty="", remittance=""):
    return {
        "credit_debit_indicator": "CRDT",
        "debtor": {"name": ""},
        "creditor": {"name": counterparty},
        "remittance_information": [remittance] if remittance else [],
    }


def test_capture_group_is_substituted_title_cased():
    tx = expense("Eigen spaarrekening", "Maandelijks spaargeld - vakantie")
    assert apply_categorization_rules(tx) == (
        ExpenseCategory.NAAR_SPAARPOTJES.value, "Sparen - Vakantie")


def test_placeholder_without_group_uses_whole_match():
    assert apply_categorization_rules(expense("PICNIC", "Bestelling")) == (
        ExpenseCategory.BOODSCHAPPEN.value, "Picnic inkopen")


def test_template_without_placeholder_is_used_verbatim():
    tx = expense("ASN Bank", "Gebruik betaalrekening")
    assert apply_categorization_rules(tx) == (
        ExpenseCategory.ABONNEMENTEN.value, "ASN Gebruikskosten")


def test_match_is_case_insensitive():
    assert apply_categorization_rules(expense("vitens nv"))[0] == (
        ExpenseCategory.GAS_WATER_ELECTRA.value)


def test_remittance_alone_can_match():
    tx = expense("", "Betaling zilveren kruis polis")
    assert apply_categorization_rules(tx)[0] == (
        ExpenseCategory.ZORGVERZEKERING.value)


def test_direction_selects_the_rule_table():
    """The same text is a different rule for income and for expenses."""
    assert apply_categorization_rules(income("Zorgverzekeraar",
                                             "Zorgkostennota 123")) == (
        IncomeCategory.PERSONLIJKE_REKENING.value, "Zorgkosten terugbetaling")
    assert apply_categorization_rules(expense("Zorgverzekeraar",
                                              "Zorgkostennota 123")) == (
        ExpenseCategory.REKENINGEN.value, "Zorgkosten terugbetaling")


def test_income_rule_does_not_fire_for_an_expense():
    assert apply_categorization_rules(expense("Werkgever", "Bonus")) == (
        None, None)


def test_no_match_returns_none_pair():
    assert apply_categorization_rules(expense("Onbekend", "xyz")) == (
        None, None)


def test_missing_fields_do_not_raise():
    assert apply_categorization_rules(
        {"credit_debit_indicator": "DBIT"}) == (None, None)


def test_duo_row_description():
    tx = income("DUO Hoofdrekening", "Studiefinanciering")
    assert apply_categorization_rules(tx) == (
        IncomeCategory.OVERHEID.value, "Duo uitkering")


def test_anamata_salary_description():
    tx = income("Anamata BV", "SALARIS SEPTEMBER")
    assert apply_categorization_rules(tx) == (
        IncomeCategory.SALARIS.value, "Salaris Ezra")


def test_no_period_marker_matches_a_written_description():
    """4.3: nothing may marker-match a sheet's Description column."""
    for description in ("Duo uitkering", "Salaris Ezra"):
        for marker in MARKERS:
            assert re.search(marker, description) is None, (marker,
                                                            description)


def test_engine_regex_pass_does_not_import_the_ui_module(monkeypatch):
    """Step 5 deletes transaction_prompt.py; the regex pass must survive."""
    monkeypatch.setitem(sys.modules, "finance_core.ui.transaction_prompt",
                        None)
    engine = CategorizationEngine(ai_enabled=False)
    assert engine._apply_regex_rules(expense("PICNIC")) == (
        ExpenseCategory.BOODSCHAPPEN.value, "Picnic inkopen")


# ── which rule fired (rule coverage report) ─────────────────────────────────

def test_first_matching_rule_names_the_pattern_that_fired():
    rule = first_matching_rule(expense("JUMBO UTRECHT"))
    assert "JUMBO" in rule.pattern
    assert rule.category is ExpenseCategory.BOODSCHAPPEN
    assert apply_categorization_rules(expense("JUMBO UTRECHT"))[0] == "Boodschappen"


def test_first_matching_rule_uses_the_income_table_for_income():
    rule = first_matching_rule(income("DUO Hoofdrekening"))
    assert rule.pattern == "DUO" and rule.category is IncomeCategory.OVERHEID


def test_first_matching_rule_is_none_without_a_match():
    assert first_matching_rule(expense("Nobody", "nothing here")) is None
