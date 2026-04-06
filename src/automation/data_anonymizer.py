"""
Data Anonymization for AI Categorization

Ensures that NO personally identifiable information (PII) is sent to external APIs.
Only the minimum data required for categorization is included.

Privacy Principles:
1. Remove all IBANs (bank account numbers)
2. Remove personal names (keep merchant/business names)
3. Remove reference numbers that could be personal
4. Keep only transaction-relevant information
5. Log what was anonymized for transparency
"""

import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class TransactionAnonymizer:
    """Anonymizes transaction data before sending to AI APIs."""

    # Common Dutch merchant/business indicators (keep these)
    BUSINESS_INDICATORS = [
        r'\bB\.?V\.?\b',  # BV
        r'\bN\.?V\.?\b',  # NV
        r'\bLtd\.?\b',
        r'\bInc\.?\b',
        r'\bCorp\.?\b',
        r'\bGmbH\b',
        r'Supermarkt',
        r'Restaurant',
        r'Cafe',
        r'Store',
        r'Shop',
        r'Market',
    ]

    # Known merchant patterns (these are safe to keep)
    KNOWN_MERCHANTS = [
        'JUMBO', 'PICNIC', 'LIDL', 'ALBERT HEIJN', 'AH to go', 'VOMAR', 'PLUS',
        'GREENWHEELS', 'NETFLIX', 'SPOTIFY', 'APPLE', 'GOOGLE',
        'NS GROEP', 'OVPAY', 'TINQ', 'TANGO',
        'ENGIE', 'VITENS', 'ODIDO', 'SIMPEL', 'VODAFONE',
        'DUO', 'GEMEENTE', 'BELASTINGDIENST',
        'ZILVEREN KRUIS', 'CHRISTELIJKE ZORG',
        'ANWB', 'CONSUMENTENBOND',
    ]

    # Patterns that indicate personal transactions (anonymize these)
    PERSONAL_PATTERNS = [
        r'\bReferentie:\s*[A-Z0-9-]+',  # Reference numbers
        r'\bIBAN:\s*[A-Z]{2}[0-9]{2}[A-Z0-9]+',  # IBANs
        r'\bNL\d{2}[A-Z]{4}\d+',  # Dutch IBANs
        # "Naam: Jan de Vries"
        r'(?:Naam|Name):\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',
        r'\bKenmerk:\s*[A-Z0-9-]+',  # Identification numbers
        r'\b\d{6,}\b',  # Long numbers (could be personal references)
    ]

    def __init__(self):
        """Initialize the anonymizer."""
        self.business_pattern = re.compile(
            '|'.join(self.BUSINESS_INDICATORS),
            re.IGNORECASE
        )
        self.merchant_pattern = re.compile(
            '|'.join(re.escape(m) for m in self.KNOWN_MERCHANTS),
            re.IGNORECASE
        )

    def anonymize_transaction(
        self, transaction: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create an anonymized copy of the transaction for AI processing.

        Only includes:
        - Transaction amount (numerical, no account info)
        - Merchant/business name (if identifiable)
        - Transaction description (sanitized)
        - Date (just the date, no time)
        - Transaction type (income/expense)

        Removes:
        - IBANs
        - Personal names
        - Reference numbers
        - Account identifiers

        Args:
            transaction: Original transaction dict

        Returns:
            Anonymized transaction dict with minimal data for categorization
        """
        # Extract amount information (safe - just numbers)
        amount_info = transaction.get('transaction_amount', {})
        amount = float(amount_info.get('amount', 0))

        # Extract transaction type (safe - just DBIT/CRDT)
        tx_type = transaction.get('credit_debit_indicator', 'UNKNOWN')

        # Extract counterparty name (check both fields, use whichever is non-empty)
        counterparty_raw = (
            transaction.get('creditor', {}).get('name', '') or
            transaction.get('debtor', {}).get('name', '')
        )
        if not counterparty_raw.strip():
            remittance = transaction.get('remittance_information', [])
            if remittance and isinstance(remittance, list):
                counterparty_raw = remittance[0][:60]
            elif remittance:
                counterparty_raw = str(remittance)[:60]

        counterparty_clean = self._anonymize_counterparty(counterparty_raw)

        # Extract and anonymize remittance information
        remittance_raw = transaction.get('remittance_information', [])
        if isinstance(remittance_raw, list):
            remittance_text = ' '.join(remittance_raw)
        else:
            remittance_text = str(remittance_raw)

        remittance_clean = self._anonymize_text(remittance_text)

        # Create anonymized transaction (ONLY what's needed for categorization)
        anonymized = {
            'transaction_amount': amount,  # Just the number
            'credit_debit_indicator': tx_type,
            'creditor': counterparty_clean,  # Anonymized merchant name
            'remittance_information': remittance_clean,  # Anonymized description
            # Just the date
            'booking_date': transaction.get('booking_date', '')
        }

        # Log what was anonymized (for transparency)
        if counterparty_raw != counterparty_clean:
            logger.info(
                f"Anonymized counterparty: '{counterparty_raw}' → '{counterparty_clean}'"
            )
        if remittance_text != remittance_clean:
            logger.debug(
                f"Anonymized remittance: '{remittance_text[:50]}...' → "
                f"'{remittance_clean[:50]}...'"
            )

        return anonymized

    def anonymize_batch(
        self, transactions: list
    ) -> tuple:
        """
        Anonymize a batch of transactions with consistent placeholder mapping.

        The same personal name gets the same placeholder across all transactions,
        enabling the AI to detect cross-transaction patterns (e.g., "Person_A sent
        3 transfers totaling X").

        Returns:
            Tuple of (anonymized_transactions, name_mapping)
            name_mapping: dict mapping placeholder -> original name
        """
        person_counter = 0
        name_to_placeholder = {}
        placeholder_to_name = {}
        results = []

        for transaction in transactions:
            amount_info = transaction.get('transaction_amount', {})
            amount = float(amount_info.get('amount', 0))
            tx_type = transaction.get('credit_debit_indicator', 'UNKNOWN')

            # Extract counterparty (both fields, fallback to remittance)
            counterparty_raw = (
                transaction.get('creditor', {}).get('name', '') or
                transaction.get('debtor', {}).get('name', '')
            )
            if not counterparty_raw.strip():
                remittance = transaction.get('remittance_information', [])
                if remittance and isinstance(remittance, list):
                    counterparty_raw = remittance[0][:60]
                elif remittance:
                    counterparty_raw = str(remittance)[:60]

            # Anonymize with consistent naming
            counterparty_clean = self._anonymize_counterparty(counterparty_raw)
            if counterparty_clean == "Private Person":
                # Assign consistent placeholder for this person
                name_key = counterparty_raw.strip().lower()
                if name_key in name_to_placeholder:
                    counterparty_clean = name_to_placeholder[name_key]
                else:
                    person_counter += 1
                    label = chr(ord('A') + (person_counter - 1) % 26)
                    if person_counter > 26:
                        label = f"{label}{person_counter // 26}"
                    placeholder = f"Person_{label}"
                    name_to_placeholder[name_key] = placeholder
                    placeholder_to_name[placeholder] = counterparty_raw.strip()
                    counterparty_clean = placeholder

            # Anonymize remittance
            remittance_raw = transaction.get('remittance_information', [])
            if isinstance(remittance_raw, list):
                remittance_text = ' '.join(remittance_raw)
            else:
                remittance_text = str(remittance_raw)
            remittance_clean = self._anonymize_text(remittance_text)

            results.append({
                'transaction_amount': amount,
                'credit_debit_indicator': tx_type,
                'creditor': counterparty_clean,
                'remittance_information': remittance_clean,
                'booking_date': transaction.get('booking_date', '')
            })

        logger.info(
            f"Batch anonymized {len(transactions)} transactions, "
            f"{len(placeholder_to_name)} unique persons masked"
        )
        return results, placeholder_to_name

    def _anonymize_counterparty(self, name: str) -> str:
        """
        Anonymize counterparty name.

        Keeps: Known merchants, businesses (with B.V., N.V., etc.)
        Removes: Personal names, unknown parties

        Args:
            name: Raw counterparty name

        Returns:
            Anonymized name or generic placeholder
        """
        if not name:
            return "Unknown"

        name = name.strip()

        # Check if it's a known merchant (keep as-is)
        if self.merchant_pattern.search(name):
            return name

        # Check if it contains business indicators (likely safe)
        if self.business_pattern.search(name):
            # Remove any trailing personal identifiers but keep business name
            # Example: "CompanyName B.V. - John Smith" → "CompanyName B.V."
            business_part = re.split(r'\s*[-–—]\s*', name)[0]
            return business_part.strip()

        # Check if it looks like a Dutch business name
        # (all caps, or contains typical business words)
        if name.isupper():
            # Likely a business name (e.g., "RESTAURANT DE EETHOEK")
            return name

        # Check if it's likely a personal name (mixed case, 2+ words with capitals)
        # Example: "Jan de Vries", "Marie Schmidt"
        words = name.split()
        if len(words) >= 2:
            # Check if it looks like "FirstName LastName" pattern
            capitalized_words = [w for w in words if w and w[0].isupper()]
            if len(capitalized_words) >= 2:
                logger.warning(f"Anonymizing personal name: {name}")
                return "Private Person"

        # Single word names or unclear - check if business-like
        if words and len(words) == 1 and len(words[0]) > 10:
            # Long single word, probably a business
            return name

        # Default: anonymize to be safe
        logger.warning(f"Anonymizing unclear counterparty: {name}")
        return "Private Person"

    def _anonymize_text(self, text: str) -> str:
        """
        Anonymize remittance information text.

        Removes:
        - IBANs
        - Reference numbers
        - Personal identifiers
        - Long numeric sequences

        Keeps:
        - Merchant names
        - Transaction descriptions
        - Generic payment information

        Args:
            text: Raw remittance text

        Returns:
            Anonymized text
        """
        if not text:
            return ""

        # Remove IBAN patterns
        text = re.sub(
            r'\bNL\d{2}[A-Z]{4}\d+\b',
            '[IBAN]',
            text,
            flags=re.IGNORECASE
        )

        # Remove reference numbers
        for pattern in self.PERSONAL_PATTERNS:
            text = re.sub(pattern, '[REF]', text)

        # Remove long sequences of digits (could be personal references)
        # But keep amounts (with currency symbols or decimal points)
        text = re.sub(
            r'(?<!\d[.,])\b\d{8,}\b(?![.,]\d)',
            '[ID]',
            text
        )

        # Normalize whitespace
        text = ' '.join(text.split())

        return text.strip()

    def get_safe_summary(self, transaction: Dict[str, Any]) -> str:
        """
        Get a privacy-safe summary of the transaction for logging.

        Args:
            transaction: Anonymized transaction

        Returns:
            Human-readable summary (safe to log)
        """
        amount = transaction.get('transaction_amount', 0)
        counterparty = transaction.get('creditor', 'Unknown')
        tx_type = 'Income' if amount > 0 else 'Expense'

        return f"{tx_type}: {counterparty} - {amount:.2f} EUR"


# Global instance
_anonymizer = TransactionAnonymizer()


def anonymize_for_ai(transaction: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to anonymize a transaction for AI processing.

    This is the main entry point for anonymization.

    Args:
        transaction: Original transaction dict

    Returns:
        Anonymized transaction dict
    """
    return _anonymizer.anonymize_transaction(transaction)


def get_anonymized_summary(transaction: Dict[str, Any]) -> str:
    """
    Get a safe summary of an anonymized transaction.

    Args:
        transaction: Anonymized transaction dict

    Returns:
        Human-readable summary
    """
    return _anonymizer.get_safe_summary(transaction)


def anonymize_batch_for_ai(transactions: list) -> tuple:
    """
    Anonymize a batch of transactions with consistent person naming.

    Returns:
        Tuple of (anonymized_transactions, name_mapping)
        name_mapping: dict mapping placeholder -> original name
    """
    return _anonymizer.anonymize_batch(transactions)
