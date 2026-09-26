"""
Regex categorisation rules: the first pass of the categorisation engine.

Moved verbatim out of the Discord review UI (removed in Phase 3) so the
regex path no longer depends on it. Pure: `re` plus the rule tables
in constants.py.
"""

import re
from typing import Any, Dict, Optional, Tuple

from constants import CATEGORIZATION_RULES_EXPENSE, CATEGORIZATION_RULES_INCOME


def apply_categorization_rules(
        transaction: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply categorization rules to suggest category and description.
    Returns (suggested_category, suggested_description) or (None, None) if no match.
    """
    # Determine transaction type
    is_income = transaction.get("credit_debit_indicator") == "CRDT"
    rules = CATEGORIZATION_RULES_INCOME if is_income else CATEGORIZATION_RULES_EXPENSE

    if not rules:
        return None, None

    # Gather text to search from various transaction fields
    search_texts = []

    # Add counterparty names
    if debtor_name := transaction.get("debtor", {}).get("name"):
        search_texts.append(debtor_name.lower())
    if creditor_name := transaction.get("creditor", {}).get("name"):
        search_texts.append(creditor_name.lower())

    # Add remittance information
    remittance = transaction.get("remittance_information", [])
    for item in remittance:
        if item:
            search_texts.append(item.lower())

    # Combine all text for searching
    combined_text = " ".join(search_texts)

    # Try each rule pattern
    for pattern, (description_template, category) in rules.items():
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match:
            # Generate description using template
            if "{c}" in description_template:
                # Extract the matched text for {c} placeholder
                matched_text = match.group(
                    1) if match.groups() else match.group(0)
                suggested_description = description_template.replace(
                    "{c}", matched_text.title())
            else:
                suggested_description = description_template

            return category.value, suggested_description

    return None, None
