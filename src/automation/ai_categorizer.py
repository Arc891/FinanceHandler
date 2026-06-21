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

    def __init__(self, api_key: Optional[str] = None, model: str = "sonnet"):
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
            logger.info(
                f"Initialized ClaudeCategorizer with Claude Code CLI (model: {model})")
        elif self.provider.api_client:
            logger.info(
                f"Initialized ClaudeCategorizer with Anthropic API (model: {model})")
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
            counterparty_orig = transaction.get(
                'creditor', {}).get('name', '')
        else:
            counterparty_orig = transaction.get(
                'debtor', {}).get('name', '')

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
                confidence_score = confidence_map.get(
                    confidence_level.lower(), 0.3)

                # Generate description using ORIGINAL counterparty name (preserves privacy locally)
                # AI suggested a description based on anonymized data, we
                # enhance it with real names
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
        category_list = "\n".join(
            [f"- {cat}" for cat in available_categories.keys()])

        # Format example rules (show 10-15 examples)
        examples = []
        for pattern, (desc_template, category) in list(
                example_rules.items())[:15]:
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

    @staticmethod
    def _build_local_description(
        original_counterparty: str, ai_description: str, category: str = ""
    ) -> str:
        """
        Build the final local description, degrading gracefully when there is
        no usable counterparty name (e.g. card/POS payments, where the merchant
        lives in the remittance and creditor/debtor name is empty).

        Args:
            original_counterparty: Original counterparty name (may be personal,
                empty, or the legacy 'Unknown' sentinel)
            ai_description: AI's suggested description (based on anonymized data)
            category: Selected category (unused; kept for call-site compat)

        Returns:
            A clean description, or "" when nothing usable could be built (the
            caller then routes the transaction to manual review).
        """
        cp = (original_counterparty or "").strip()
        if cp.lower() == "unknown":
            cp = ""
        desc = (ai_description or "").strip()

        # Anonymized person placeholder: restore the real name if we have one,
        # otherwise drop the placeholder without leaving dangling separators.
        if "Private Person" in desc:
            if cp:
                return desc.replace("Private Person", cp).strip()
            return desc.replace("Private Person", "").strip(" -–—|").strip()

        # No real counterparty: the AI description already carries the merchant.
        if not cp:
            return desc

        # Counterparty name already present in the description -> keep it.
        if cp in desc:
            return desc

        # Have a name but no AI description -> the name alone is meaningful.
        if not desc:
            return cp

        # Default: prepend counterparty for context ("Jan de Vries - ...").
        return f"{cp} - {desc}"

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
                logger.warning(
                    f"Missing required fields in response: {result}")
                return None

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response text: {response_text}")
            return None

    async def categorize_batch(
        self,
        transactions_to_categorize: list,
        precategorized_transactions: list,
        expense_categories: Dict[str, str],
        income_categories: Dict[str, str],
        example_rules: Dict[str, Tuple[str, str]]
    ) -> list:
        """
        Categorize a batch of transactions in a single AI call.

        Returns list of (category, description, confidence, relationship_info) tuples.
        Returns None at positions where categorization failed.
        """
        from automation.data_anonymizer import anonymize_batch_for_ai

        if not transactions_to_categorize:
            return []

        # Anonymize all transactions with consistent naming
        all_transactions = precategorized_transactions + transactions_to_categorize
        anonymized_all, name_mapping = anonymize_batch_for_ai(all_transactions)

        anon_precategorized = anonymized_all[:len(precategorized_transactions)]
        anon_to_categorize = anonymized_all[len(precategorized_transactions):]

        # Build expected T-ids
        expected_ids = [f"T{i+1}" for i in range(len(anon_to_categorize))]

        # Chunk if needed
        chunk_size = 40
        if len(anon_to_categorize) <= chunk_size:
            chunks = [(anon_to_categorize, transactions_to_categorize, expected_ids)]
        else:
            chunks = self._build_chunks(
                anon_to_categorize, transactions_to_categorize, expected_ids, chunk_size)

        all_results = [None] * len(transactions_to_categorize)
        offset = 0

        for chunk_anon, chunk_orig, chunk_ids in chunks:
            prompt = self._build_batch_prompt(
                chunk_anon, anon_precategorized, precategorized_transactions,
                expense_categories, income_categories, example_rules, chunk_ids
            )

            try:
                response_text = await self.provider.complete(
                    prompt=prompt, max_tokens=8192, temperature=0.3)

                parsed, missing_ids = self._parse_batch_response(
                    response_text, chunk_ids,
                    list(expense_categories.keys()) + list(income_categories.keys()))

                # Repair if needed
                if missing_ids and parsed is not None:
                    logger.warning(f"Partial failure: {len(missing_ids)} missing IDs, attempting repair")
                    repaired = await self._repair_batch_response(
                        None, f"{len(missing_ids)} transactions missing",
                        missing_ids, chunk_anon, chunk_ids,
                        expense_categories, income_categories)
                    if repaired:
                        parsed.update(repaired)
                        missing_ids = [tid for tid in chunk_ids if tid not in parsed]

                elif parsed is None:
                    logger.warning("Total parse failure, attempting repair")
                    parsed_repair, still_missing = self._parse_batch_response(
                        "", chunk_ids,
                        list(expense_categories.keys()) + list(income_categories.keys()))
                    repaired = await self._repair_batch_response(
                        response_text[:2000], "JSON parse failed",
                        chunk_ids, chunk_anon, chunk_ids,
                        expense_categories, income_categories)
                    if repaired:
                        parsed = repaired
                        missing_ids = [tid for tid in chunk_ids if tid not in parsed]
                    else:
                        missing_ids = chunk_ids

                # Map results back
                for i, tid in enumerate(chunk_ids):
                    idx = offset + i
                    if parsed and tid in parsed:
                        entry = parsed[tid]
                        confidence_map = {'high': 0.9, 'medium': 0.6, 'low': 0.3}
                        conf = confidence_map.get(
                            entry.get('confidence', 'low').lower(), 0.3)

                        # De-anonymize description
                        orig_tx = chunk_orig[i]
                        counterparty_orig = (
                            orig_tx.get('creditor', {}).get('name', '') or
                            orig_tx.get('debtor', {}).get('name', ''))
                        ai_desc = entry.get('description', '')
                        final_desc = self._build_local_description(
                            counterparty_orig, ai_desc, entry.get('category', ''))

                        # De-anonymize description_suffix
                        suffix = entry.get('description_suffix')
                        if suffix:
                            for placeholder, real_name in name_mapping.items():
                                suffix = suffix.replace(placeholder, real_name)

                        relationship = None
                        if entry.get('linked_to') or suffix:
                            relationship = {
                                'linked_to': entry.get('linked_to', []),
                                'description_suffix': suffix
                            }

                        all_results[idx] = (
                            entry.get('category'),
                            final_desc,
                            conf,
                            relationship
                        )

            except Exception as e:
                logger.error(f"Batch categorization chunk failed: {e}", exc_info=True)
                # Leave None entries for this chunk — caller handles fallback

            offset += len(chunk_ids)

        return all_results

    def _build_chunks(self, anon_txs, orig_txs, ids, chunk_size):
        """Split transactions into chunks, avoiding splitting same counterparty."""
        chunks = []
        i = 0
        while i < len(anon_txs):
            end = min(i + chunk_size, len(anon_txs))
            # Try not to split same counterparty
            if end < len(anon_txs):
                current_cp = anon_txs[end - 1].get('creditor', '')
                while end < len(anon_txs) and anon_txs[end].get('creditor', '') == current_cp:
                    end += 1
                    if end - i > chunk_size + 10:
                        break  # Safety limit
            chunks.append((anon_txs[i:end], orig_txs[i:end], ids[i:end]))
            i = end
        return chunks

    def _build_batch_prompt(
        self, anon_to_categorize, anon_precategorized, orig_precategorized,
        expense_categories, income_categories, example_rules, t_ids
    ) -> str:
        """Build the batch categorization prompt."""
        # Format categories
        expense_list = "\n".join(f"- {cat}" for cat in expense_categories.keys())
        income_list = "\n".join(f"- {cat}" for cat in income_categories.keys())

        # Format example rules (up to 30)
        examples = []
        for pattern, (desc_template, category) in list(example_rules.items())[:30]:
            examples.append(f"- {pattern} → {category} (\"{desc_template}\")")
        example_text = "\n".join(examples)

        # Format precategorized context (deduplicate if >50)
        precat_rows = []
        seen = set()
        for anon_tx, orig_tx in zip(anon_precategorized, orig_precategorized):
            cat = orig_tx.get('category', '?')
            cp = anon_tx.get('creditor', 'Unknown')
            key = f"{cp}|{cat}"
            if key in seen and len(precat_rows) >= 50:
                continue
            seen.add(key)
            tx_type = "INCOME" if anon_tx.get('credit_debit_indicator') == 'CRDT' else "EXPENSE"
            precat_rows.append(
                f"| C{len(precat_rows)+1} | {anon_tx.get('booking_date', '?')} "
                f"| {tx_type} | {anon_tx.get('transaction_amount', 0):.2f} "
                f"| {cp} | {cat} |"
            )
            if len(precat_rows) >= 50:
                break

        precat_text = "\n".join(precat_rows) if precat_rows else "(none)"

        # Format transactions to categorize
        to_cat_rows = []
        for tid, anon_tx in zip(t_ids, anon_to_categorize):
            tx_type = "INCOME" if anon_tx.get('credit_debit_indicator') == 'CRDT' else "EXPENSE"
            to_cat_rows.append(
                f"| {tid} | {anon_tx.get('booking_date', '?')} "
                f"| {tx_type} | {anon_tx.get('transaction_amount', 0):.2f} "
                f"| {anon_tx.get('creditor', 'Unknown')} "
                f"| {anon_tx.get('remittance_information', '')[:80]} |"
            )
        to_cat_text = "\n".join(to_cat_rows)

        return f"""You are a transaction categorization assistant for Dutch household budgets.

## Available Categories
### Expense:
{expense_list}

### Income:
{income_list}

## Example Rules (reference - shows how similar transactions are categorized):
{example_text}

## Pre-Categorized Transactions (READ-ONLY context - do NOT change these):
| # | Date | Type | Amount EUR | Counterparty | Category |
|---|------|------|-----------|--------------|----------|
{precat_text}

## Transactions to Categorize:
| # | Date | Type | Amount EUR | Counterparty | Description |
|---|------|------|-----------|--------------|-------------|
{to_cat_text}

## Instructions:
1. Categorize each T-transaction. Use EXACT category names from the lists above.
2. Description: concise, IN DUTCH, max 50 characters.
3. Confidence: high / medium / low.
4. **Relationship Detection**:
   a. If income transfers (from savings/personal accounts) sum to match an expense
      amount (within 0.02 EUR), they are likely related. Link them:
      - Income descriptions: append "(voor [expense name])"
      - Expense description: append "(deels uit spaarpot)"
      - Income from savings accounts → use "Spaarrekening" category
   b. Same counterparty across transactions → use consistent categories.
5. Pre-categorized (C-rows) are final. Use them for context only.

## Response (JSON only, no markdown code blocks):
{{"transactions": [
  {{"id": "T1", "category": "...", "description": "...", "confidence": "high|medium|low",
   "reasoning": "...", "linked_to": ["T2","T3"], "description_suffix": "(deels uit spaarpot)"}},
  ...
]}}

Respond ONLY with the JSON object. Description must be in DUTCH."""

    def _parse_batch_response(self, response_text, expected_ids, valid_categories):
        """
        Parse batch AI response.

        Returns (parsed_dict, missing_ids) where parsed_dict maps T-id to entry dict.
        Returns (None, all_ids) on total parse failure.
        """
        try:
            # Extract JSON (handle markdown code blocks)
            json_text = response_text.strip()
            if "```json" in json_text:
                start = json_text.find("```json") + 7
                end = json_text.find("```", start)
                json_text = json_text[start:end].strip()
            elif "```" in json_text:
                start = json_text.find("```") + 3
                end = json_text.find("```", start)
                json_text = json_text[start:end].strip()

            result = json.loads(json_text)

            if 'transactions' not in result:
                logger.warning("Batch response missing 'transactions' key")
                return None, list(expected_ids)

            parsed = {}
            for entry in result['transactions']:
                tid = entry.get('id')
                if not tid:
                    continue
                if not all(k in entry for k in ('category', 'description', 'confidence')):
                    logger.warning(f"Entry {tid} missing required fields")
                    continue
                # Validate category
                if entry['category'] not in valid_categories:
                    logger.warning(
                        f"Entry {tid} has invalid category '{entry['category']}', keeping anyway")
                parsed[tid] = entry

            missing = [tid for tid in expected_ids if tid not in parsed]
            if missing:
                logger.warning(f"Batch response missing {len(missing)} IDs: {missing}")

            return parsed, missing

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse batch JSON: {e}")
            return None, list(expected_ids)

    async def _repair_batch_response(
        self, malformed_response, error_msg, missing_ids,
        anon_transactions, all_ids, expense_categories, income_categories
    ):
        """
        Attempt to repair a failed batch response.

        For partial failure: requests only missing transactions.
        For total failure: sends truncated malformed response with category lists.

        Returns dict mapping T-id to entry, or None on failure.
        """
        expense_list = ", ".join(expense_categories.keys())
        income_list = ", ".join(income_categories.keys())

        if malformed_response is None:
            # Partial failure - only request missing
            missing_data = []
            for tid in missing_ids:
                idx = all_ids.index(tid)
                tx = anon_transactions[idx]
                tx_type = "INCOME" if tx.get('credit_debit_indicator') == 'CRDT' else "EXPENSE"
                missing_data.append(
                    f"| {tid} | {tx.get('booking_date', '?')} | {tx_type} "
                    f"| {tx.get('transaction_amount', 0):.2f} | {tx.get('creditor', '?')} "
                    f"| {tx.get('remittance_information', '')[:60]} |")

            prompt = f"""You previously categorized transactions but missed some. Categorize ONLY these:

Valid expense categories: {expense_list}
Valid income categories: {income_list}

| # | Date | Type | Amount EUR | Counterparty | Description |
|---|------|------|-----------|--------------|-------------|
{chr(10).join(missing_data)}

Response (JSON only, no markdown):
{{"transactions": [{{"id": "T5", "category": "...", "description": "...", "confidence": "high|medium|low"}}]}}"""

        else:
            # Total failure
            prompt = f"""Your previous response was malformed JSON:
{malformed_response}

Error: {error_msg}

Valid expense categories: {expense_list}
Valid income categories: {income_list}

Return ONLY valid JSON:
{{"transactions": [{{"id": "T1", "category": "...", "description": "...", "confidence": "high|medium|low"}}]}}"""

        try:
            response = await self.provider.complete(
                prompt=prompt, max_tokens=10240, temperature=0.2)

            valid_cats = list(expense_categories.keys()) + list(income_categories.keys())
            parsed, still_missing = self._parse_batch_response(
                response, missing_ids, valid_cats)
            if still_missing:
                logger.warning(f"Repair still missing {len(still_missing)} IDs")
            return parsed

        except Exception as e:
            logger.error(f"Repair attempt failed: {e}")
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
    for pattern, (desc_template,
                  category_enum) in categorization_rules.items():
        # Extract category name from enum
        category_name = str(
            category_enum.value) if hasattr(
            category_enum,
            'value') else str(category_enum)
        examples[pattern] = (desc_template, category_name)

    return examples
