#!/usr/bin/env python3
"""
Test script for batch AI categorization.
Runs the categorization engine against a test CSV without the Discord bot.

Usage:
    cd src && python -m scripts.test_batch_categorization
    # or from project root:
    source venv/bin/activate && cd src && python ../scripts/test_batch_categorization.py
"""

import sys
import os
import asyncio
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'src'))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Reduce noise from libraries
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('google').setLevel(logging.WARNING)


async def main():
    csv_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'data', 'test_batch.csv')

    if not os.path.exists(csv_path):
        print(f"Test CSV not found: {csv_path}")
        return

    # Load transactions
    from finance_core.csv_helper import load_transactions_from_csv
    transactions = load_transactions_from_csv(csv_path)
    print(f"\n{'='*70}")
    print(f"Loaded {len(transactions)} transactions from test CSV")
    print(f"{'='*70}\n")

    # Show all transactions
    for i, tx in enumerate(transactions, 1):
        amount = tx['transaction_amount']['amount']
        indicator = tx['credit_debit_indicator']
        counterparty = (tx.get('debtor', {}).get('name') or
                        tx.get('creditor', {}).get('name') or '(empty)')
        remittance = tx.get('remittance_information', [''])[0][:50]
        print(f"  {i:2d}. {tx['booking_date']} | {amount:>9s} | "
              f"{'INC' if indicator == 'CRDT' else 'EXP'} | "
              f"{counterparty[:30]:<30s} | {remittance}")

    # Initialize categorization engine
    print(f"\n{'='*70}")
    print("Initializing categorization engine...")
    print(f"{'='*70}\n")

    from finance_core.categorization_engine import create_categorization_engine
    engine = create_categorization_engine(ai_enabled=True)

    if not engine.ai_enabled:
        print("WARNING: AI is not enabled. Only regex categorization will run.")
        print("Make sure Claude CLI is available or set CLAUDE_API_KEY.")

    # Run batch categorization
    print(f"\n{'='*70}")
    print("Running batch categorization...")
    print(f"{'='*70}\n")

    results = await engine.batch_categorize(transactions)

    # Display results
    print(f"\n{'='*70}")
    print("RESULTS")
    print(f"{'='*70}\n")

    regex_count = 0
    ai_auto_count = 0
    ai_manual_count = 0
    none_count = 0
    linked_count = 0

    for i, (tx, result) in enumerate(zip(transactions, results), 1):
        amount = tx['transaction_amount']['amount']
        indicator = tx['credit_debit_indicator']
        counterparty = (tx.get('debtor', {}).get('name') or
                        tx.get('creditor', {}).get('name') or '(empty)')

        method_emoji = {
            'regex': '📋', 'ai_auto': '🤖', 'ai_manual_needed': '❓', 'none': '❌'
        }.get(result.method, '?')

        conf_pct = f"{int(result.confidence * 100)}%"

        # Build description with suffix
        desc = result.description or ''
        if result.description_suffix:
            desc = f"{desc} {result.description_suffix}"

        linked = ""
        if result.linked_transactions:
            linked = f" [linked: {result.linked_transactions}]"
            linked_count += 1

        print(f"  {i:2d}. {method_emoji} {result.method:<18s} | "
              f"{conf_pct:>4s} | {result.category or '(none)':<25s} | "
              f"{desc[:50]}{linked}")

        if result.method == 'regex':
            regex_count += 1
        elif result.method == 'ai_auto':
            ai_auto_count += 1
        elif result.method == 'ai_manual_needed':
            ai_manual_count += 1
        else:
            none_count += 1

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"  Total:          {len(results)}")
    print(f"  Regex:          {regex_count}")
    print(f"  AI Auto:        {ai_auto_count}")
    print(f"  AI Manual:      {ai_manual_count}")
    print(f"  None:           {none_count}")
    print(f"  With links:     {linked_count}")
    print(f"  Would upload:   {regex_count + ai_auto_count}")
    print(f"  Needs review:   {ai_manual_count + none_count}")


if __name__ == '__main__':
    asyncio.run(main())
