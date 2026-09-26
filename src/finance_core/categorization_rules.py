"""
Categorisation rules: the first pass of the categorisation engine.

In order, first match wins:
1. the conditional rules in constants.py (a pattern plus a condition, e.g.
   the role of the sending account);
2. the rule tables in constants.py, moved verbatim out of the Discord
   review UI (removed in Phase 3);
3. the household's own rules in the local rules file (local_rules.py),
   which were chosen on the rows 1 and 2 leave uncovered. A local rule may
   mark its row for the user to check, or send the row to the AI.
"""

import re
from enum import Enum
from typing import Any, Dict, NamedTuple, Optional, Tuple

from constants import (
    CATEGORIZATION_RULES_EXPENSE,
    CATEGORIZATION_RULES_INCOME,
    CONDITIONAL_RULES_EXPENSE,
    CONDITIONAL_RULES_INCOME,
)
from finance_core.local_rules import default_local_rules
from finance_core.rule_conditions import parse_when
from finance_core.tx_features import tx_direction

_CONDITIONAL = {
    direction: [(pattern, parse_when(when), template, category)
                for pattern, when, (template, category) in table]
    for direction, table in (("out", CONDITIONAL_RULES_EXPENSE), ("in", CONDITIONAL_RULES_INCOME))
}


class Rule(NamedTuple):
    """The first rule that matched a transaction, and its match."""
    pattern: str
    match: re.Match
    template: str
    category: Enum
    marked: bool = False


def search_text(transaction: Dict[str, Any]) -> str:
    """The lower-cased text the rules search: counterparty names, then remittance."""
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

    return " ".join(search_texts)


def first_matching_rule(transaction: Dict[str, Any], local_rules=None) -> Optional[Rule]:
    """The first rule that matches the transaction, or None (the AI decides).

    `local_rules` defaults to the configured local rules file; an `ai` line
    there that matches ends the search with None.
    """
    direction = tx_direction(transaction)
    combined_text = search_text(transaction)

    for pattern, when, template, category in _CONDITIONAL[direction]:
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match and when(transaction):
            return Rule(pattern, match, template, category)

    table = CATEGORIZATION_RULES_INCOME if direction == "in" else CATEGORIZATION_RULES_EXPENSE
    for pattern, (description_template, category) in table.items():
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match:
            return Rule(pattern, match, description_template, category)

    for rule in default_local_rules() if local_rules is None else local_rules:
        if rule.direction != direction:
            continue
        match = rule.regex.search(combined_text)
        if match and rule.when(transaction):
            if rule.category is None:
                return None
            return Rule(rule.pattern, match, rule.description, rule.category, rule.marked)

    return None


def _description(rule: Rule) -> str:
    if "{c}" not in rule.template:
        return rule.template
    # The first group, or the whole match, title-cased.
    matched_text = rule.match.group(1) if rule.match.groups() else rule.match.group(0)
    return rule.template.replace("{c}", matched_text.title())


def rule_result(transaction: Dict[str, Any], local_rules=None
                ) -> Optional[Tuple[str, str, bool]]:
    """(category, description, marked) from the first matching rule, or None."""
    rule = first_matching_rule(transaction, local_rules)
    if rule is None:
        return None
    return rule.category.value, _description(rule), rule.marked


def apply_categorization_rules(
        transaction: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply categorization rules to suggest category and description.
    Returns (suggested_category, suggested_description) or (None, None) if no match.
    """
    got = rule_result(transaction)
    return (got[0], got[1]) if got else (None, None)
