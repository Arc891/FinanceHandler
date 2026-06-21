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
    reasoning: Optional[str] = None
    linked_transactions: Optional[list] = None  # indices of related transactions
    description_suffix: Optional[str] = None  # e.g. "(voor Roompot)"


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

    def _decide_method(self, confidence: float, description: str) -> str:
        """
        Decide whether an AI result can auto-upload or needs manual review.

        Requires both sufficient confidence AND a non-blank description: a
        transaction with no usable description should be reviewed (and given
        one) rather than auto-uploaded with an empty/junk label.
        """
        if confidence >= self.ai_confidence_threshold and (
                description or "").strip():
            return 'ai_auto'
        return 'ai_manual_needed'

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
            method = self._decide_method(confidence, description)
            if method == 'ai_auto':
                logger.info(
                    f"AI auto-approved: {category} - {description} "
                    f"(confidence: {confidence:.2f})"
                )
            else:
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
        Categorize a batch: regex first on all, then batch AI for unmatched.

        Returns list of CategorizationResult, one per input transaction.
        """
        results: list[Optional[CategorizationResult]] = [None] * len(transactions)

        # Pass 1: regex on all transactions
        regex_matched = []  # (index, tx, result)
        unmatched = []      # (index, tx)

        for i, tx in enumerate(transactions):
            cat, desc = self._apply_regex_rules(tx)
            if cat:
                result = CategorizationResult(
                    category=cat, description=desc,
                    confidence=1.0, method='regex')
                results[i] = result
                regex_matched.append((i, tx, result))
            else:
                unmatched.append((i, tx))

        logger.info(
            f"Regex pass: {len(regex_matched)} matched, "
            f"{len(unmatched)} need AI")

        # Pass 2: batch AI for unmatched
        if self.ai_enabled and self.ai_categorizer and unmatched:
            try:
                from constants import (
                    ExpenseCategory, IncomeCategory,
                    CATEGORIZATION_RULES_EXPENSE, CATEGORIZATION_RULES_INCOME
                )
                from automation.ai_categorizer import get_example_rules_for_ai

                expense_categories = {
                    cat.value: cat.value for cat in ExpenseCategory
                    if cat != ExpenseCategory.DUMMY_CACHED}
                income_categories = {
                    cat.value: cat.value for cat in IncomeCategory
                    if cat != IncomeCategory.DUMMY_CACHED}

                # Combine rules for examples
                all_rules = {**CATEGORIZATION_RULES_EXPENSE, **CATEGORIZATION_RULES_INCOME}
                example_rules = get_example_rules_for_ai(all_rules)

                # Build precategorized context
                precategorized = []
                for _, tx, result in regex_matched:
                    precategorized.append({
                        **tx, "category": result.category,
                        "description": result.description
                    })

                unmatched_txs = [tx for _, tx in unmatched]

                logger.info(
                    f"Sending {len(unmatched_txs)} transactions to AI "
                    f"(with {len(precategorized)} precategorized as context)")

                ai_results = await self.ai_categorizer.categorize_batch(
                    transactions_to_categorize=unmatched_txs,
                    precategorized_transactions=precategorized,
                    expense_categories=expense_categories,
                    income_categories=income_categories,
                    example_rules=example_rules
                )

                # Map AI results back and handle fallback for failures
                for j, (orig_idx, orig_tx) in enumerate(unmatched):
                    ai_result = ai_results[j] if j < len(ai_results) else None

                    if ai_result is None:
                        # Batch failed for this tx — fall back to individual
                        logger.info(f"Falling back to per-tx AI for index {orig_idx}")
                        fallback = await self._apply_ai_categorization(orig_tx)
                        results[orig_idx] = fallback
                    else:
                        category, description, confidence, relationship = ai_result
                        method = self._decide_method(confidence, description)

                        suffix = None
                        linked = None
                        if relationship:
                            suffix = relationship.get('description_suffix')
                            linked_ids = relationship.get('linked_to', [])
                            if linked_ids:
                                linked = linked_ids

                        results[orig_idx] = CategorizationResult(
                            category=category, description=description,
                            confidence=confidence, method=method,
                            description_suffix=suffix,
                            linked_transactions=linked)

                # Pass 3: apply relationship annotations to regex-matched
                self._apply_relationship_annotations(
                    results, unmatched, ai_results)

            except Exception as e:
                logger.error(f"Batch AI failed: {e}", exc_info=True)
                # Fall back to per-transaction for all unmatched
                for orig_idx, orig_tx in unmatched:
                    if results[orig_idx] is None:
                        fallback = await self._apply_ai_categorization(orig_tx)
                        results[orig_idx] = fallback

        # Fill remaining None results
        for i, r in enumerate(results):
            if r is None:
                results[i] = CategorizationResult(
                    category=None, description=None,
                    confidence=0.0, method='none')

        # Log statistics
        total = len(results)
        stats = {}
        for r in results:
            stats[r.method] = stats.get(r.method, 0) + 1
        logger.info(f"Batch complete: {total} transactions - {stats}")

        return results

    def _apply_relationship_annotations(
        self, results, unmatched, ai_results
    ):
        """Apply relationship suffixes to regex-matched transactions if linked."""
        # Build a map from T-id to unmatched index
        tid_to_unmatched_idx = {}
        for j, (orig_idx, _) in enumerate(unmatched):
            tid_to_unmatched_idx[f"T{j+1}"] = orig_idx

        for j, ai_result in enumerate(ai_results or []):
            if ai_result is None:
                continue
            _, _, _, relationship = ai_result
            if not relationship:
                continue

            linked_ids = relationship.get('linked_to', [])
            suffix = relationship.get('description_suffix')

            for linked_id in linked_ids:
                if linked_id.startswith('C'):
                    # Links to a regex-matched transaction
                    # C-ids are 1-based into precategorized list
                    try:
                        c_idx = int(linked_id[1:]) - 1
                        if 0 <= c_idx < len(results) and results[c_idx] is not None:
                            # Don't change category, just add suffix
                            if suffix and results[c_idx].method == 'regex':
                                results[c_idx].description_suffix = suffix
                                logger.info(
                                    f"Added relationship suffix to regex tx C{c_idx+1}: {suffix}")
                    except (ValueError, IndexError):
                        pass


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
