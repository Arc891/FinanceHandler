"""
Tests for finance_core.flagging and the placeholder handling of plan 4.9
(Phase 3 step 2). Replaces the review-flow tests: nothing is held back for
review any more, an uncertain row is written flagged with the
`! Nog in te delen !` category of its block.

That the discarded AI guess reaches the run state and the summary is
tested with the pipeline in tests/test_process_upload.py (step 3); here the
guess is the value category_for hands the pipeline. All rows are synthetic.
"""

import pytest

from constants import ExpenseCategory, IncomeCategory
from finance_core import categorization_engine as ce
from finance_core.categorization_engine import (
    CategorizationEngine,
    CategorizationResult,
    ai_category_options,
)
from finance_core.flagging import (
    PLACEHOLDER,
    apply_category,
    category_for,
    full_description,
)
from fakes import expense_tx, income_tx

METHODS = ("regex", "ai_auto", "ai_manual_needed", "none")


def raw(tx):
    """A transaction as csv_helper yields it: no description or category yet."""
    return {k: v for k, v in tx.items() if k not in ("description", "category")}


def result(method, category="Boodschappen", description="Picnic inkopen",
           confidence=0.9, suffix=None):
    return CategorizationResult(category=category, description=description,
                                confidence=confidence, method=method,
                                description_suffix=suffix)


# ── constants ────────────────────────────────────────────────────────────────

def test_income_placeholder_exists_and_is_the_default():
    assert IncomeCategory.NOG_IN_TEDELEN.value == "! Nog in te delen !"
    assert IncomeCategory.DEFAULT is IncomeCategory.NOG_IN_TEDELEN
    assert ExpenseCategory.DEFAULT is ExpenseCategory.NOG_IN_TEDELEN


def test_both_placeholders_share_the_sheet_label():
    assert PLACEHOLDER == ExpenseCategory.NOG_IN_TEDELEN.value
    assert PLACEHOLDER == IncomeCategory.NOG_IN_TEDELEN.value


# ── category_for ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method", ["regex", "ai_auto"])
def test_confident_results_keep_their_category(method):
    assert category_for(result(method), is_income=False) == (
        "Boodschappen", "Picnic inkopen", None)


@pytest.mark.parametrize("method", ["ai_manual_needed", "none"])
@pytest.mark.parametrize("is_income, placeholder", [
    (False, ExpenseCategory.NOG_IN_TEDELEN.value),
    (True, IncomeCategory.NOG_IN_TEDELEN.value),
])
def test_uncertain_results_get_the_placeholder_of_their_block(
        method, is_income, placeholder):
    category, _, guess = category_for(result(method, confidence=0.6),
                                      is_income=is_income)
    assert category == placeholder
    assert guess == {"ai_category": "Boodschappen", "ai_confidence": 0.6}


def test_uncertain_income_is_not_filed_as_a_personal_account_transfer():
    category, _, _ = category_for(result("ai_manual_needed", category="Gift"),
                                  is_income=True)
    assert category != IncomeCategory.PERSONLIJKE_REKENING.value
    assert category == IncomeCategory.NOG_IN_TEDELEN.value


def test_ai_description_survives_onto_a_flagged_row():
    _, description, _ = category_for(
        result("ai_manual_needed", description="Etentje", suffix="(voor X)"),
        is_income=False)
    assert description == "Etentje (voor X)"


def test_flagged_row_without_any_description_returns_none():
    _, description, _ = category_for(
        result("none", category=None, description=None, confidence=0.0),
        is_income=False)
    assert description is None


def test_result_with_no_ai_guess_records_an_empty_guess():
    _, _, guess = category_for(
        result("none", category=None, description=None, confidence=0.0),
        is_income=False)
    assert guess == {"ai_category": None, "ai_confidence": 0.0}


@pytest.mark.parametrize("method", ["regex", "ai_auto"])
def test_confident_placeholder_answer_is_still_flagged(method):
    """Belt and braces: the flagged count must equal the placeholder rows."""
    category, _, guess = category_for(
        result(method, category=PLACEHOLDER, confidence=0.9), is_income=True)
    assert category == IncomeCategory.NOG_IN_TEDELEN.value
    assert guess == {"ai_category": PLACEHOLDER, "ai_confidence": 0.9}


def test_full_description_joins_the_suffix():
    assert full_description(result("regex", suffix="(deels uit spaarpot)")) == (
        "Picnic inkopen (deels uit spaarpot)")
    assert full_description(result("regex", description=None)) == ""
    assert full_description(result("regex", description=None,
                                    suffix="(x)")) == "(x)"


# ── apply_category: the row as it goes to the sheet ─────────────────────────

@pytest.mark.parametrize("method", METHODS)
def test_no_code_path_holds_a_row_back(method):
    tx = raw(expense_tx())
    row, _ = apply_category(tx, result(method, confidence=0.3))
    assert row["category"]
    assert row["booking_date"] == tx["booking_date"]
    assert row["transaction_amount"] == tx["transaction_amount"]


def test_apply_category_does_not_modify_its_input():
    tx = raw(expense_tx())
    before = dict(tx)
    apply_category(tx, result("regex"))
    assert tx == before


def test_flagged_row_without_description_falls_back_to_bank_text():
    from finance_core.google_sheets import format_transaction_for_sheet
    tx = raw(expense_tx(name="Bakkerij", rem="Pinbetaling 12"))
    row, guess = apply_category(
        tx, result("none", category=None, description=None, confidence=0.0))
    assert "description" not in row
    assert guess is not None
    assert format_transaction_for_sheet(row)[2:] == [
        "Bakkerij - Pinbetaling 12", PLACEHOLDER]


def test_income_row_gets_the_income_placeholder():
    row, guess = apply_category(raw(income_tx()),
                                result("ai_manual_needed", category="Gift"))
    assert row["category"] == IncomeCategory.NOG_IN_TEDELEN.value
    assert guess["ai_category"] == "Gift"


def test_confident_row_carries_no_guess():
    row, guess = apply_category(raw(expense_tx()), result("ai_auto"))
    assert (row["category"], row["description"], guess) == (
        "Boodschappen", "Picnic inkopen", None)


# ── the AI's option list ─────────────────────────────────────────────────────

def test_ai_category_options_exclude_both_placeholders_and_cached():
    expense, income = ai_category_options()
    for options in (expense, income):
        assert PLACEHOLDER not in options
        assert "CACHED" not in options
    assert "Boodschappen" in expense and "Salaris" in income


class RecordingAI:
    """Captures the category dictionaries the engine hands the model."""

    def __init__(self):
        self.seen = []

    async def categorize_batch(self, transactions_to_categorize,
                               precategorized_transactions, expense_categories,
                               income_categories, example_rules, **kwargs):
        self.seen.append((expense_categories, income_categories))
        return [None] * len(transactions_to_categorize)

    async def categorize_transaction(self, transaction, expense_categories,
                                     income_categories, example_rules):
        self.seen.append((expense_categories, income_categories))
        return "Ander", "iets", 0.9


async def test_neither_ai_path_is_offered_a_placeholder():
    ai = RecordingAI()
    engine = CategorizationEngine(ai_categorizer=ai, ai_enabled=True)
    await engine.batch_categorize([raw(expense_tx(name="Onbekend", rem="x"))])
    assert len(ai.seen) == 2        # the batch call, then the per-row fallback
    for expense, income in ai.seen:
        assert PLACEHOLDER not in expense
        assert PLACEHOLDER not in income


# ── the threshold ────────────────────────────────────────────────────────────

def test_threshold_is_read_from_config(monkeypatch):
    monkeypatch.setattr(ce, "setting", lambda name, default=None: (
        0.6 if name == "AI_CONFIDENCE_THRESHOLD" else default))
    engine = ce.create_categorization_engine(ai_enabled=False)
    assert engine.ai_confidence_threshold == 0.6


def test_explicit_threshold_overrides_config(monkeypatch):
    monkeypatch.setattr(ce, "setting", lambda name, default=None: 0.6)
    engine = ce.create_categorization_engine(ai_enabled=False,
                                             ai_confidence_threshold=0.9)
    assert engine.ai_confidence_threshold == 0.9


def test_row_exactly_at_the_threshold_is_not_flagged():
    engine = CategorizationEngine(ai_confidence_threshold=0.6)
    method = engine._decide_method(0.6, "Etentje")
    assert method == "ai_auto"
    _, _, guess = category_for(result(method, confidence=0.6), is_income=False)
    assert guess is None


def test_row_below_the_threshold_is_flagged():
    engine = CategorizationEngine(ai_confidence_threshold=0.75)
    method = engine._decide_method(0.6, "Etentje")
    _, _, guess = category_for(result(method, confidence=0.6), is_income=False)
    assert guess is not None
