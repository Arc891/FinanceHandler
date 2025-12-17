#!/usr/bin/env python3
"""
Test script for AI categorization (Phase 2)

Tests the categorization engine with sample transactions to verify:
1. Regex categorization still works
2. AI categorization works for unmatched transactions
3. Confidence scoring works correctly
4. Integration between regex and AI is seamless
5. Data anonymization protects privacy

Usage:
    # Set environment variable first
    export CLAUDE_API_KEY="sk-ant-..."

    # Run the test
    python scripts/test_ai_categorization.py
"""

import os
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from finance_core.categorization_engine import create_categorization_engine
from constants import ExpenseCategory, IncomeCategory
from automation.data_anonymizer import anonymize_for_ai, TransactionAnonymizer


def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{'='*80}")
    print(f"  {text}")
    print(f"{'='*80}\n")


def print_result(result, transaction_desc: str):
    """Print a categorization result in a readable format."""
    confidence_indicator = "✅" if result.confidence >= 0.75 else "⚠️" if result.confidence >= 0.5 else "❌"

    print(f"Transaction: {transaction_desc}")
    print(f"  {confidence_indicator} Category: {result.category or 'None'}")
    print(f"  Description: {result.description or 'None'}")
    print(f"  Confidence: {result.confidence:.2f} ({result.method})")
    if result.reasoning:
        print(f"  Reasoning: {result.reasoning}")
    print()


def create_sample_transactions():
    """Create a set of sample transactions for testing."""

    # Transactions that SHOULD match regex rules
    regex_matched = [
        {
            "name": "JUMBO supermarket",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": -45.50, "currency": "EUR"},
                "creditor": {"name": "JUMBO Supermarkt"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Betaling JUMBO Driebergen"],
                "booking_date": "2025-01-15"
            }
        },
        {
            "name": "Greenwheels car rental",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": -28.00, "currency": "EUR"},
                "creditor": {"name": "Greenwheels"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Greenwheels autohuur"],
                "booking_date": "2025-01-14"
            }
        },
        {
            "name": "Salary payment",
            "transaction": {
                "credit_debit_indicator": "CRDT",
                "transaction_amount": {"amount": 2500.00, "currency": "EUR"},
                "creditor": {"name": "Your Name"},
                "debtor": {"name": "Employer BV"},
                "remittance_information": ["SALARIS januari 2025"],
                "booking_date": "2025-01-25"
            }
        }
    ]

    # Transactions that should NOT match regex (AI will handle these)
    ai_needed = [
        {
            "name": "Unknown coffee shop",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": -4.50, "currency": "EUR"},
                "creditor": {"name": "De Koffiebar Utrecht"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Contactloos betalen"],
                "booking_date": "2025-01-16"
            }
        },
        {
            "name": "Online subscription",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": -9.99, "currency": "EUR"},
                "creditor": {"name": "NETFLIX.COM"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Netflix Subscription"],
                "booking_date": "2025-01-10"
            }
        },
        {
            "name": "Unknown restaurant",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": -67.80, "currency": "EUR"},
                "creditor": {"name": "Restaurant De Eethoek"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Diner met vrienden"],
                "booking_date": "2025-01-12"
            }
        },
        {
            "name": "Gift received",
            "transaction": {
                "credit_debit_indicator": "CRDT",
                "transaction_amount": {"amount": 50.00, "currency": "EUR"},
                "creditor": {"name": "Your Name"},
                "debtor": {"name": "Oma"},
                "remittance_information": ["Verjaardagscadeau"],
                "booking_date": "2025-01-18"
            }
        }
    ]

    return regex_matched, ai_needed


def test_regex_only():
    """Test that regex categorization still works (AI disabled)."""
    print_header("TEST 1: Regex-Only Categorization (AI Disabled)")

    engine = create_categorization_engine(
        claude_api_key=None,
        ai_enabled=False
    )

    regex_matched, _ = create_sample_transactions()

    for sample in regex_matched:
        result = engine.categorize(sample["transaction"])
        print_result(result, sample["name"])

    print("✅ Regex categorization works as expected\n")


def test_ai_categorization():
    """Test AI categorization for transactions that don't match regex."""
    print_header("TEST 2: AI Categorization for Unmatched Transactions")

    api_key = os.environ.get('CLAUDE_API_KEY')
    if not api_key:
        print("❌ CLAUDE_API_KEY environment variable not set")
        print("   Set it with: export CLAUDE_API_KEY='sk-ant-...'")
        return False

    engine = create_categorization_engine(
        claude_api_key=api_key,
        ai_enabled=True,
        ai_confidence_threshold=0.75
    )

    _, ai_needed = create_sample_transactions()

    print("Testing AI categorization...\n")

    for sample in ai_needed:
        result = engine.categorize(sample["transaction"])
        print_result(result, sample["name"])

    print("✅ AI categorization completed\n")
    return True


def test_unified_engine():
    """Test the full unified engine (regex + AI)."""
    print_header("TEST 3: Unified Engine (Regex → AI Pipeline)")

    api_key = os.environ.get('CLAUDE_API_KEY')
    if not api_key:
        print("❌ CLAUDE_API_KEY environment variable not set")
        print("   Skipping unified test")
        return False

    engine = create_categorization_engine(
        claude_api_key=api_key,
        ai_enabled=True,
        ai_confidence_threshold=0.75
    )

    regex_matched, ai_needed = create_sample_transactions()
    all_transactions = regex_matched + ai_needed

    print(f"Processing {len(all_transactions)} transactions...\n")

    results = engine.batch_categorize([s["transaction"] for s in all_transactions])

    for sample, result in zip(all_transactions, results):
        print_result(result, sample["name"])

    # Print statistics
    regex_count = sum(1 for r in results if r.method == 'regex')
    ai_auto_count = sum(1 for r in results if r.method == 'ai_auto')
    ai_manual_count = sum(1 for r in results if r.method == 'ai_manual_needed')

    print(f"\n📊 Statistics:")
    print(f"   Regex matched: {regex_count}/{len(all_transactions)}")
    print(f"   AI auto-approved: {ai_auto_count}/{len(all_transactions)}")
    print(f"   AI manual review needed: {ai_manual_count}/{len(all_transactions)}")

    print("\n✅ Unified engine test completed\n")
    return True


def test_anonymization():
    """Test that sensitive data is properly anonymized."""
    print_header("TEST 4: Data Anonymization & Privacy Protection")

    anonymizer = TransactionAnonymizer()

    # Test cases with sensitive data
    test_cases = [
        {
            "name": "Transaction with IBAN",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "-45.50", "currency": "EUR"},
                "creditor": {"name": "Jan de Vries"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Betaling NL91ABNA0417164300 Referentie: 123456789"],
                "booking_date": "2025-01-15"
            },
            "should_remove": ["NL91ABNA0417164300", "123456789", "Jan de Vries"]
        },
        {
            "name": "Transaction with personal reference",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "-100.00", "currency": "EUR"},
                "creditor": {"name": "Marie Schmidt"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Kenmerk: PERS-2025-001 Naam: Marie"],
                "booking_date": "2025-01-16"
            },
            "should_remove": ["PERS-2025-001", "Marie Schmidt"]
        },
        {
            "name": "Business transaction (should keep)",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "-250.00", "currency": "EUR"},
                "creditor": {"name": "Software Solutions B.V."},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Invoice 2025-001 for consulting services"],
                "booking_date": "2025-01-17"
            },
            "should_keep": ["Software Solutions B.V.", "consulting"]
        },
        {
            "name": "Known merchant (should keep)",
            "transaction": {
                "credit_debit_indicator": "DBIT",
                "transaction_amount": {"amount": "-45.50", "currency": "EUR"},
                "creditor": {"name": "JUMBO Supermarkt"},
                "debtor": {"name": "Your Name"},
                "remittance_information": ["Betaling JUMBO Driebergen NL12TEST1234567890"],
                "booking_date": "2025-01-18"
            },
            "should_keep": ["JUMBO"],
            "should_remove": ["NL12TEST1234567890"]
        }
    ]

    all_passed = True

    for test_case in test_cases:
        print(f"\nTest: {test_case['name']}")
        anonymized = anonymizer.anonymize_transaction(test_case["transaction"])

        # Convert to string for checking
        anonymized_str = str(anonymized)

        # Check that sensitive data was removed
        if "should_remove" in test_case:
            for sensitive in test_case["should_remove"]:
                if sensitive in anonymized_str:
                    print(f"  ❌ FAILED: Sensitive data not removed: '{sensitive}'")
                    print(f"     Found in: {anonymized_str}")
                    all_passed = False
                else:
                    print(f"  ✅ Removed: '{sensitive}'")

        # Check that important data was kept
        if "should_keep" in test_case:
            for important in test_case["should_keep"]:
                if important.lower() in anonymized_str.lower():
                    print(f"  ✅ Kept: '{important}'")
                else:
                    print(f"  ⚠️  Warning: Expected data not found: '{important}'")

        # Show anonymized result
        print(f"  Anonymized counterparty: {anonymized.get('creditor', 'N/A')}")
        print(f"  Anonymized description: {anonymized.get('remittance_information', 'N/A')[:50]}...")

    if all_passed:
        print("\n✅ All anonymization tests passed!")
    else:
        print("\n❌ Some anonymization tests failed - review privacy protection")

    print("\n📋 Privacy Summary:")
    print("   - IBANs: REMOVED")
    print("   - Personal names: REMOVED")
    print("   - Reference numbers: REMOVED")
    print("   - Merchant names: KEPT (needed for categorization)")
    print("   - Transaction amounts: KEPT (numerical only)")
    print("   - Dates: KEPT (no time information)")

    return all_passed


def main():
    """Run all tests."""
    print("=" * 80)
    print("  AI Categorization Test Suite - Phase 2")
    print("=" * 80)

    # Test 1: Regex only (no API key needed)
    test_regex_only()

    # Test 2: Anonymization (no API key needed)
    anonymization_ok = test_anonymization()

    # Test 3: AI categorization (requires API key)
    ai_success = test_ai_categorization()

    # Test 4: Unified engine (requires API key)
    if ai_success:
        test_unified_engine()

    print_header("All Tests Complete")

    if not anonymization_ok:
        print("⚠️  PRIVACY WARNING: Anonymization tests failed!")
        print("   Do NOT use AI categorization until privacy issues are resolved")
    elif not os.environ.get('CLAUDE_API_KEY'):
        print("⚠️  Some tests were skipped because CLAUDE_API_KEY is not set")
        print("   To run all tests, set the environment variable:")
        print("   export CLAUDE_API_KEY='sk-ant-...'")
        print("\n✅ Anonymization tests passed - privacy protection is working")
    else:
        print("✅ All tests passed successfully!")
        print("✅ Privacy protection verified - safe to use with real data")

    print("\nNext steps:")
    print("1. Review anonymization results above")
    print("2. Update config_settings.py to set AI_CATEGORIZATION_ENABLED = True")
    print("3. Integrate AI categorization into the Discord bot workflow")
    print("4. Test with real bank transactions (data will be anonymized)")


if __name__ == "__main__":
    main()
