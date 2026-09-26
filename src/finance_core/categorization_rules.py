"""
Regex categorisation rules: the first pass of the categorisation engine.

Moved verbatim out of the Discord review UI (removed in Phase 3) so the
regex path no longer depends on it. Pure: `re` plus the rule tables
in constants.py.
"""

import re
from enum import Enum
from typing import Any, Dict, NamedTuple, Optional, Tuple

from constants import CATEGORIZATION_RULES_EXPENSE, CATEGORIZATION_RULES_INCOME


class Rule(NamedTuple):
    """The first rule that matched a transaction, and its match."""
    pattern: str
    match: re.Match
    template: str
    category: Enum


def first_matching_rule(transaction: Dict[str, Any]) -> Optional[Rule]:
    """The first rule of the transaction's table that matches it, or None."""
    # Determine transaction type
    is_income = transaction.get("credit_debit_indicator") == "CRDT"
    rules = CATEGORIZATION_RULES_INCOME if is_income else CATEGORIZATION_RULES_EXPENSE

    if not rules:
        return None

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
            return Rule(pattern, match, description_template, category)

    return None


def apply_categorization_rules(
        transaction: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply categorization rules to suggest category and description.
    Returns (suggested_category, suggested_description) or (None, None) if no match.
    """
    rule = first_matching_rule(transaction)
    if rule is None:
        return None, None

    # Generate description using template
    if "{c}" in rule.template:
        # Extract the matched text for {c} placeholder
        matched_text = rule.match.group(
            1) if rule.match.groups() else rule.match.group(0)
        suggested_description = rule.template.replace(
            "{c}", matched_text.title())
    else:
        suggested_description = rule.template

    return rule.category.value, suggested_description
