"""
AI-powered transaction categorization using Claude API.

This module provides intelligent categorization for transactions that don't
match existing regex rules. Uses Claude 3.5 Haiku for cost-efficient processing.

PRIVACY: All transaction data is anonymized before being sent to the API.
See data_anonymizer.py for details on what is removed/kept.
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple
from automation.data_anonymizer import anonymize_for_ai, get_anonymized_summary
from automation.claude_provider import ClaudeProvider

# Configure logging with color
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ClaudeCategorizer:
    """Categorizes transactions using Claude API with confidence scoring."""

    def __init__(self, api_key: Optional[str] = None, model: str = "haiku"):
        """
        Initialize the Claude categorizer.

        Tries Claude Code CLI first (free), falls back to API if provided.

        Args:
            api_key: Optional Anthropic API key (for API fallback)
            model: Model alias (haiku, sonnet, opus) - default: haiku for cost efficiency
        """
        self.provider = ClaudeProvider(api_key=api_key, model=model)
        self.model = model

        if self.provider.use_cli:
            logger.info(f"Initialized ClaudeCategorizer with Claude Code CLI (model: {model})")
        elif self.provider.api_client:
            logger.info(f"Initialized ClaudeCategorizer with Anthropic API (model: {model})")
        else:
            raise ValueError(
                "No Claude access available. Install Claude Code or set CLAUDE_API_KEY."
            )

    async def categorize_transaction(
        self,
        transaction: Dict[str, Any],
        expense_categories: Dict[str, str],
        income_categories: Dict[str, str],
        example_rules: Dict[str, Tuple[str, str]]
    ) -> Tuple[Optional[str], Optional[str], float]:
        """
        Categorize a transaction using Claude API.

        PRIVACY: Transaction data is ANONYMIZED before being sent to the API.
        Personal names, IBANs, and reference numbers are removed. Only merchant
        names and transaction descriptions needed for categorization are included.

        Args:
            transaction: Transaction dict with keys:
                - transaction_amount: dict with 'amount' and 'currency'
                - credit_debit_indicator: 'CRDT' or 'DBIT'
                - creditor/debtor: dict with 'name'
                - remittance_information: list of strings
                - booking_date: str (transaction date)
            expense_categories: Dict mapping category names to descriptions
            income_categories: Dict mapping category names to descriptions
            example_rules: Dict of example patterns for reference

        Returns:
            Tuple of (category, description, confidence_score)
            - category: Categorized category name or None
            - description: Generated description or None
            - confidence: Float 0.0-1.0 (high=0.9, medium=0.6, low=0.3)
        """
        # ANONYMIZE the transaction before processing (for API call only)
        anonymized_tx = anonymize_for_ai(transaction)

        # Extract data from ANONYMIZED transaction (for AI prompt)
        amount = anonymized_tx.get('transaction_amount', 0)
        counterparty_anon = anonymized_tx.get('creditor', 'Unknown')
        description_anon = anonymized_tx.get('remittance_information', '')

        # Extract ORIGINAL counterparty (for local description)
        amount_orig = transaction.get('transaction_amount', {})
        if isinstance(amount_orig, dict):
            amount_value = float(amount_orig.get('amount', 0))
        else:
            amount_value = float(amount_orig)

        is_expense = amount_value < 0
        if is_expense:
            counterparty_orig = transaction.get('creditor', {}).get('name', 'Unknown')
        else:
            counterparty_orig = transaction.get('debtor', {}).get('name', 'Unknown')

        # Determine if income or expense
        is_income = amount > 0
        available_categories = income_categories if is_income else expense_categories
        transaction_type = "income" if is_income else "expense"

        # Log using safe anonymized summary
        safe_summary = get_anonymized_summary(anonymized_tx)
        logger.info(f"Categorizing (anonymized): {safe_summary}")

        # Build the prompt with ANONYMIZED data
        prompt = self._build_prompt(
            amount=amount,
            counterparty=counterparty_anon,
            description=description_anon,
            transaction_type=transaction_type,
            available_categories=available_categories,
            example_rules=example_rules
        )

        try:
            # Call Claude (CLI or API) - async to avoid blocking Discord bot
            response_text = await self.provider.complete(
                prompt=prompt,
                max_tokens=500,
                temperature=0.3  # Lower temperature for more consistent categorization
            )

            logger.debug(f"Claude response: {response_text}")

            # Extract JSON from response
            result = self._parse_response(response_text)

            if result:
                category = result.get('category')
                ai_description = result.get('description')
                confidence_level = result.get('confidence', 'low')

                # Map confidence level to numeric score
                confidence_map = {
                    'high': 0.9,
                    'medium': 0.6,
                    'low': 0.3
                }
                confidence_score = confidence_map.get(confidence_level.lower(), 0.3)

                # Generate description using ORIGINAL counterparty name (preserves privacy locally)
                # AI suggested a description based on anonymized data, we enhance it with real names
                final_description = self._build_local_description(
                    counterparty_orig, ai_description, category
                )

                logger.info(
                    f"AI categorized: {category} | {final_description} | "
                    f"Confidence: {confidence_level} ({confidence_score})"
                )

                return category, final_description, confidence_score
            else:
                logger.warning("Failed to parse Claude response")
                return None, None, 0.0

        except Exception as e:
            logger.error(f"Error calling Claude API: {e}")
            return None, None, 0.0

    def _build_prompt(
        self,
        amount: float,
        counterparty: str,
        description: str,
        transaction_type: str,
        available_categories: Dict[str, str],
        example_rules: Dict[str, Tuple[str, str]]
    ) -> str:
        """Build the prompt for Claude API."""

        # Format available categories
        category_list = "\n".join([f"- {cat}" for cat in available_categories.keys()])

        # Format example rules (show 10-15 examples)
        examples = []
        for pattern, (desc_template, category) in list(example_rules.items())[:15]:
            examples.append(f"- {pattern} → {category} (\"{desc_template}\")")
        example_text = "\n".join(examples)

        prompt = f"""You are a transaction categorization assistant for Dutch household budgets.

**Transaction Type**: {transaction_type.upper()}

**Available Categories**:
{category_list}

**Transaction Details**:
- Amount: {amount:.2f} EUR
- Counterparty: {counterparty}
- Description: {description}

**Examples from existing rules** (for reference):
{example_text}

**Instructions**:
1. Analyze the transaction and choose the MOST appropriate category from the available list
2. Generate a concise description IN DUTCH (max 50 characters) that clearly identifies the transaction
3. Assess your confidence level:
   - HIGH: Very clear match (e.g., well-known merchant, obvious category)
   - MEDIUM: Reasonable match (e.g., can infer from context)
   - LOW: Uncertain match (e.g., unclear merchant, ambiguous description)

**Response Format** (JSON only, no other text):
{{
  "category": "exact category name from available list",
  "description": "concise Dutch description max 50 chars",
  "confidence": "high|medium|low",
  "reasoning": "brief explanation why you chose this category"
}}

Respond ONLY with the JSON object, nothing else. Remember: description must be in DUTCH."""

        return prompt

    def _build_local_description(
        self, original_counterparty: str, ai_description: str, category: str
    ) -> str:
        """
        Build final description using original (non-anonymized) counterparty name.

        This preserves personal context in local bookkeeping while keeping
        the AI's categorization logic.

        Args:
            original_counterparty: Original counterparty name (may be personal)
            ai_description: AI's suggested description (based on anonymized data)
            category: Selected category

        Returns:
            Description with original counterparty name for local storage
        """
        # If AI's description contains "Private Person", replace with original name
        if "Private Person" in ai_description:
            return ai_description.replace("Private Person", original_counterparty)

        # If original name is already in AI description, keep it
        if original_counterparty in ai_description:
            return ai_description

        # Otherwise, prepend original counterparty for context
        # Example: "Jan de Vries - Payment received"
        return f"{original_counterparty} - {ai_description}"

    def _parse_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Parse Claude's JSON response."""
        try:
            # Try to find JSON in the response
            # Sometimes Claude wraps JSON in markdown code blocks
            if "```json" in response_text:
                # Extract JSON from code block
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_text = response_text[start:end].strip()
            elif "```" in response_text:
                # Extract from generic code block
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                json_text = response_text[start:end].strip()
            else:
                # Assume entire response is JSON
                json_text = response_text.strip()

            result = json.loads(json_text)

            # Validate required fields
            if 'category' in result and 'description' in result and 'confidence' in result:
                return result
            else:
                logger.warning(f"Missing required fields in response: {result}")
                return None

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response text: {response_text}")
            return None


def get_example_rules_for_ai(
    categorization_rules: Dict[str, Tuple[str, Any]]
) -> Dict[str, Tuple[str, str]]:
    """
    Convert categorization rules to a format suitable for AI examples.

    Args:
        categorization_rules: Dict from constants.py (pattern -> (desc, category))

    Returns:
        Dict with pattern -> (description_template, category_name)
    """
    examples = {}
    for pattern, (desc_template, category_enum) in categorization_rules.items():
        # Extract category name from enum
        category_name = str(category_enum.value) if hasattr(category_enum, 'value') else str(category_enum)
        examples[pattern] = (desc_template, category_name)

    return examples
