#!/usr/bin/env python3
"""
Script to retry failed transactions that couldn't be uploaded due to sheet size limits.
Uses bulk upload (single API call per type) instead of the background queue.

IMPORTANT: Stop the bot container before running this script to avoid concurrent writes.
"""

import sys
import os
import logging

# Add the src directory to Python path so we can import modules
# Go up one level from scripts/ to project root, then into src/
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

from finance_core.background_upload import (
    get_failed_uploads,
    clear_failed_uploads,
    get_upload_queue
)
from finance_core.google_sheets import GoogleSheetsExporter
from finance_core.session_management import load_session, save_session
from config.config_settings import GOOGLE_CREDENTIALS_PATH

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def collect_transactions(user_id):
    """Collect and deduplicate all failed transactions from recovery file + session"""
    expenses = []
    incomes = []
    seen = set()

    def dedup_key(tx):
        """Create a dedup key from transaction content"""
        date = tx.get('booking_date', '')
        amount = tx.get('transaction_amount', {}).get('amount', '')
        desc = tx.get('description', '')
        category = tx.get('category', '')
        return f"{date}|{amount}|{desc}|{category}"

    # From recovery file
    for item in get_failed_uploads(user_id):
        tx = item.get('transaction', {})
        if not tx.get('category'):
            continue
        key = dedup_key(tx)
        if key in seen:
            continue
        seen.add(key)
        if item.get('transaction_type') == 'income':
            incomes.append(tx)
        else:
            expenses.append(tx)

    # From session (legacy)
    remaining, session_income, session_expenses = load_session(user_id)
    for tx in session_expenses:
        if not tx.get('category'):
            continue
        key = dedup_key(tx)
        if key not in seen:
            seen.add(key)
            expenses.append(tx)
    for tx in session_income:
        if not tx.get('category'):
            continue
        key = dedup_key(tx)
        if key not in seen:
            seen.add(key)
            incomes.append(tx)

    return expenses, incomes, remaining


def main():
    if len(sys.argv) != 2:
        print("Usage: python retry_failed_transactions.py <user_id>")
        print("Example: python retry_failed_transactions.py 1395443068227948630")
        sys.exit(1)

    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print("Error: user_id must be a valid integer")
        sys.exit(1)

    logger.warning("⚠️  IMPORTANT: Make sure the bot container is stopped before running!")
    logger.warning("⚠️  Concurrent writes to the same sheet can cause data corruption.")
    logger.info(f"🔄 Starting retry process for user {user_id}")

    try:
        expenses, incomes, remaining = collect_transactions(user_id)
        total = len(expenses) + len(incomes)

        if total == 0:
            logger.info("ℹ️ No failed transactions found. Nothing to retry.")
            return

        logger.info(f"📊 Found {total} unique failed transactions: "
                     f"{len(expenses)} expenses, {len(incomes)} income")

        # Show examples
        for label, txs in [("expense", expenses), ("income", incomes)]:
            if txs:
                logger.info(f"📝 Example {label} transactions:")
                for i, tx in enumerate(txs[:3]):
                    desc = tx.get('description', 'Unknown')
                    amount = tx.get('transaction_amount', {}).get('amount', '?')
                    category = tx.get('category', 'No category')
                    logger.info(f"  {i+1}. {desc} - €{amount} - {category}")
                if len(txs) > 3:
                    logger.info(f"  ... and {len(txs) - 3} more")

        # Set up exporter and detect positions
        logger.info("🔍 Connecting to Google Sheets and detecting positions...")
        exporter = GoogleSheetsExporter(GOOGLE_CREDENTIALS_PATH)
        sheet = exporter._get_worksheet()

        # Detect current last rows
        queue = get_upload_queue()
        queue.exporter = exporter
        queue._detect_current_positions(user_id)
        expense_start = queue.current_expense_row
        income_start = queue.current_income_row
        logger.info(f"📍 Will write expenses starting at row {expense_start}, "
                     f"income starting at row {income_start}")

        # Ensure sheet has enough rows
        max_needed = max(
            expense_start + len(expenses) - 1,
            income_start + len(incomes) - 1
        )
        if max_needed > sheet.row_count:
            new_size = max_needed + 50
            logger.info(f"📏 Expanding sheet from {sheet.row_count} to {new_size} rows...")
            sheet.resize(rows=new_size)

        # Bulk upload expenses
        if expenses:
            rows = [exporter.format_transaction_for_sheet(tx) for tx in expenses]
            end_row = expense_start + len(rows) - 1
            target_range = f"B{expense_start}:E{end_row}"
            logger.info(f"📤 Uploading {len(rows)} expenses to {target_range}...")
            sheet.update(rows, target_range)
            logger.info(f"✅ Uploaded {len(rows)} expenses")

        # Bulk upload incomes
        if incomes:
            rows = [exporter.format_transaction_for_sheet(tx) for tx in incomes]
            end_row = income_start + len(rows) - 1
            target_range = f"G{income_start}:J{end_row}"
            logger.info(f"📤 Uploading {len(rows)} income transactions to {target_range}...")
            sheet.update(rows, target_range)
            logger.info(f"✅ Uploaded {len(rows)} income transactions")

        # Save new positions
        from finance_core.session_management import save_sheet_positions
        new_expense_row = expense_start + len(expenses)
        new_income_row = income_start + len(incomes)
        try:
            from config.config_settings import GSHEET_NAME
        except ImportError:
            GSHEET_NAME = None
        save_sheet_positions(user_id, new_expense_row, new_income_row,
                             sheet_name=GSHEET_NAME)
        logger.info(f"💾 Saved new positions: expenses={new_expense_row}, "
                     f"income={new_income_row}")

        # Clear recovery file and session failed transactions
        cleared = clear_failed_uploads(user_id)
        save_session(user_id, remaining, [], [])
        logger.info(f"🧹 Cleared {cleared} entries from recovery file and "
                     f"session failed transactions")

        # Sort the sheet
        logger.info("📊 Sorting sheet by date...")
        expense_sorted, income_sorted = exporter.sort_transactions_by_date()
        logger.info(f"✅ Sorted {expense_sorted} expenses, {income_sorted} income")

        logger.info("✅ Retry process completed successfully!")

    except Exception as e:
        logger.error(f"❌ Error during retry process: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
