"""
What the pipeline writes for a categorisation result (plan 4.9).

Every row is written. A result the engine was not confident about is written
with the `! Nog in te delen !` category of its block, and the AI's guess is
handed back so the run state and the summary can keep it; the sheet is the
only review surface left.
"""

from typing import Any, Dict, Optional, Tuple

from constants import ExpenseCategory, IncomeCategory

PLACEHOLDER = ExpenseCategory.NOG_IN_TEDELEN.value
_PLACEHOLDERS = {ExpenseCategory.NOG_IN_TEDELEN.value,
                 IncomeCategory.NOG_IN_TEDELEN.value}


def full_description(result) -> str:
    """The result's description with its relationship suffix, if any."""
    return " ".join(p for p in (result.description, result.description_suffix)
                    if p).strip()


def category_for(result, is_income: bool
                 ) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
    """Returns (category, description, discarded_ai_guess).

    The guess is None exactly when the row is not flagged. A confident
    result whose category is a placeholder still counts as flagged, so the
    flagged count equals the placeholder rows in the sheet.
    """
    if (result.method in ("regex", "ai_auto")
            and result.category not in _PLACEHOLDERS):
        return result.category, full_description(result), None
    placeholder = (IncomeCategory.NOG_IN_TEDELEN if is_income
                   else ExpenseCategory.NOG_IN_TEDELEN).value
    return placeholder, full_description(result) or None, {
        "ai_category": result.category,
        "ai_confidence": result.confidence,
    }


def apply_category(tx: Dict[str, Any], result
                   ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """The row as it goes to the sheet, plus the discarded AI guess if flagged.

    Without a description the row carries none, so
    format_transaction_for_sheet falls back to counterparty plus remittance.
    """
    is_income = tx.get("credit_debit_indicator") == "CRDT"
    category, description, guess = category_for(result, is_income)
    row = {k: v for k, v in tx.items() if k != "description"}
    row["category"] = category
    if description:
        row["description"] = description
    return row, guess
