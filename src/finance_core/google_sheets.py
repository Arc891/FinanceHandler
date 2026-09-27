# finance_core/google_sheets.py

from typing import List, Dict, Any


def format_transaction_for_sheet(transaction: Dict[str, Any]) -> List[Any]:
    """
    Format a single transaction for Google Sheets export.

    Args:
        transaction: Transaction dict with category field added

    Returns:
        List of values: [date, amount, description, category]
        Note: amount is returned as float for proper Google Sheets formatting
    """
    # Extract date
    date_str = transaction.get("booking_date", "")

    # Extract and format amount
    amount_data = transaction.get("transaction_amount", {})
    amount_str = amount_data.get("amount", "0")
    try:
        amount = float(amount_str)
        # Check if transaction was manually switched from its original type
        if transaction.get("manually_switched", False):
            # If switched, use negative of the absolute amount to represent
            # the opposite flow
            amount_value = -abs(amount)
        else:
            # Normal case: use absolute amount
            amount_value = abs(amount)
    except ValueError:
        amount_value = 0.0

    # Extract description from multiple sources
    description_parts = []

    # Check for provided description first (highest priority)
    if user_desc := transaction.get("description"):
        description_parts.append(user_desc)
    else:
        # Fallback to auto-extracting from bank data
        # Add counterparty information
        debtor_name = transaction.get("debtor", {}).get("name", "")
        creditor_name = transaction.get("creditor", {}).get("name", "")
        counterparty = debtor_name or creditor_name
        if counterparty:
            description_parts.append(counterparty)

        # Add remittance information
        remittance = transaction.get("remittance_information", [])
        if remittance and remittance[0]:
            description_parts.append(remittance[0])

    # Combine description parts
    description = " - ".join(
        description_parts) if description_parts else "Unknown Transaction"

    # Truncate description if too long (Google Sheets cell limit)
    if len(description) > 500:
        description = description[:497] + "..."

    # Get category (should have been added during categorization)
    category = transaction.get("category", "Uncategorized")

    return [date_str, amount_value, description, category]
