"""
Unified Categorization Engine

Combines regex-based auto-categorization with AI-powered categorization
for a complete transaction categorization solution.

Flow:
1. Try regex rules (existing logic) → if match, confidence = 1.0
2. If no regex match, try AI categorization → confidence based on AI response
3. Return structured result with category, description, confidence, and method
"""

import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

from automation.ai_categorizer import ClaudeCategorizer

logger = logging.getLogger(__name__)


@dataclass
class CategorizationResult:
    """Structured result from categorization engine."""
    category: Optional[str]
    description: Optional[str]
    confidence: float  # 0.0 to 1.0
    method: str  # 'regex', 'ai_auto', 'ai_manual_needed', 'none'
    reasoning: Optional[str] = None  # Only populated for AI categorizations


class CategorizationEngine:
    """
    Unified engine for transaction categorization.

    Combines regex rules with AI categorization for maximum coverage.
    """

    def __init__(
        self,
        ai_categorizer: ClaudeCategorizer | None = None,
        ai_confidence_threshold: float = 0.75,
        ai_enabled: bool = False
    ):
        """
        Initialize the categorization engine.

        Args:
            ai_categorizer: Optional ClaudeCategorizer instance
            ai_confidence_threshold: Minimum confidence for auto-approval (0.0-1.0)
            ai_enabled: Whether AI categorization is enabled
        """
        self.ai_categorizer = ai_categorizer
        self.ai_confidence_threshold = ai_confidence_threshold
        self.ai_enabled = ai_enabled

        if self.ai_enabled and not self.ai_categorizer:
            logger.warning(
                "AI categorization is enabled but no AI categorizer provided. "
                "Only regex categorization will work."
            )

        logger.info(
            f"Initialized CategorizationEngine - "
            f"AI: {self.ai_enabled}, Threshold: {ai_confidence_threshold}"
        )

    async def categorize(
            self, transaction: Dict[str, Any]) -> CategorizationResult:
        """
        Categorize a transaction using regex → AI pipeline.

        Args:
            transaction: Transaction dict with required fields:
                - credit_debit_indicator: 'CRDT' or 'DBIT'
                - transaction_amount: dict with 'amount' and 'currency'
                - creditor/debtor: dict with 'name'
                - remittance_information: list of strings
                - booking_date: str

        Returns:
            CategorizationResult with category, description, confidence, and method
        """
        # Step 1: Try regex categorization
        regex_category, regex_description = self._apply_regex_rules(
            transaction)

        if regex_category:
            logger.info(f"Regex match: {regex_category} - {regex_description}")
            return CategorizationResult(
                category=regex_category,
                description=regex_description,
                confidence=1.0,
                method='regex'
            )

        # Step 2: Try AI categorization (if enabled)
        if self.ai_enabled and self.ai_categorizer:
            return await self._apply_ai_categorization(transaction)

        # Step 3: No categorization available
        logger.info("No categorization match found (regex failed, AI disabled)")
        return CategorizationResult(
            category=None,
            description=None,
            confidence=0.0,
            method='none'
        )

    def _apply_regex_rules(
        self, transaction: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Apply regex categorization rules.

        This is the existing logic from transaction_prompt.py.
        Returns (category, description) or (None, None) if no match.
        """
        try:
            # Import here to avoid circular dependency
            from finance_core.ui.transaction_prompt import apply_categorization_rules
            return apply_categorization_rules(transaction)
        except Exception as e:
            logger.error(f"Error applying regex rules: {e}")
            return None, None

    async def _apply_ai_categorization(
        self, transaction: Dict[str, Any]
    ) -> CategorizationResult:
        """
        Apply AI categorization using Claude API (async version).

        Returns CategorizationResult with AI predictions and confidence.
        """
        try:
            # Import categories and rules
            from constants import (
                ExpenseCategory,
                IncomeCategory,
                CATEGORIZATION_RULES_EXPENSE,
                CATEGORIZATION_RULES_INCOME
            )
            from automation.ai_categorizer import get_example_rules_for_ai

            # Determine transaction type
            is_income = transaction.get("credit_debit_indicator") == "CRDT"

            # Get available categories
            expense_categories = {
                cat.value: cat.value for cat in ExpenseCategory if cat != ExpenseCategory.DUMMY_CACHED}
            income_categories = {
                cat.value: cat.value for cat in IncomeCategory if cat != IncomeCategory.DUMMY_CACHED}

            # Get example rules for AI context
            rules = CATEGORIZATION_RULES_INCOME if is_income else CATEGORIZATION_RULES_EXPENSE
            example_rules = get_example_rules_for_ai(rules)

            # Call AI categorizer (async to avoid blocking Discord bot)
            category, description, confidence = await self.ai_categorizer.categorize_transaction(
                transaction=transaction,
                expense_categories=expense_categories,
                income_categories=income_categories,
                example_rules=example_rules
            )

            if not category:
                logger.warning("AI categorization returned no result")
                return CategorizationResult(
                    category=None,
                    description=None,
                    confidence=0.0,
                    method='none'
                )

            # Determine if AI is confident enough for auto-approval
            if confidence >= self.ai_confidence_threshold:
                method = 'ai_auto'
                logger.info(
                    f"AI auto-approved: {category} - {description} "
                    f"(confidence: {confidence:.2f})"
                )
            else:
                method = 'ai_manual_needed'
                logger.info(
                    f"AI needs manual review: {category} - {description} "
                    f"(confidence: {confidence:.2f})"
                )

            return CategorizationResult(
                category=category,
                description=description,
                confidence=confidence,
                method=method
            )

        except Exception as e:
            logger.error(f"Error in AI categorization: {e}", exc_info=True)
            return CategorizationResult(
                category=None,
                description=None,
                confidence=0.0,
                method='none'
            )

    async def batch_categorize(
        self, transactions: list[Dict[str, Any]]
    ) -> list[CategorizationResult]:
        """
        Categorize a batch of transactions (async version).

        Args:
            transactions: List of transaction dicts

        Returns:
            List of CategorizationResult objects
        """
        results = []
        for tx in transactions:
            result = await self.categorize(tx)
            results.append(result)

        # Log batch statistics
        total = len(results)
        regex_count = sum(1 for r in results if r.method == 'regex')
        ai_auto_count = sum(1 for r in results if r.method == 'ai_auto')
        ai_manual_count = sum(
            1 for r in results if r.method == 'ai_manual_needed')
        none_count = sum(1 for r in results if r.method == 'none')

        logger.info(
            f"Batch categorization complete: {total} transactions - "
            f"Regex: {regex_count}, AI Auto: {ai_auto_count}, "
            f"AI Manual: {ai_manual_count}, None: {none_count}"
        )

        return results


def create_categorization_engine(
    claude_api_key: Optional[str] = None,
    ai_enabled: bool = False,
    ai_confidence_threshold: float = 0.75
) -> CategorizationEngine:
    """
    Factory function to create a categorization engine with optional AI.

    Args:
        claude_api_key: Optional Claude API key (not required if Claude Code CLI available)
        ai_enabled: Whether to enable AI categorization
        ai_confidence_threshold: Minimum confidence for auto-approval

    Returns:
        Configured CategorizationEngine instance
    """
    ai_categorizer = None

    if ai_enabled:
        try:
            from automation.ai_categorizer import ClaudeCategorizer
            # API key is optional - ClaudeCategorizer will use CLI if available
            ai_categorizer = ClaudeCategorizer(api_key=claude_api_key)
            logger.info("AI categorization enabled")
        except Exception as e:
            logger.error(f"Failed to initialize AI categorizer: {e}")
            logger.info("Falling back to regex-only categorization")
            ai_enabled = False

    return CategorizationEngine(
        ai_categorizer=ai_categorizer,
        ai_confidence_threshold=ai_confidence_threshold,
        ai_enabled=ai_enabled
    )
