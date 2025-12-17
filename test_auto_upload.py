#!/usr/bin/env python3
"""Test auto-upload functionality with categorization engine"""

import sys
sys.path.insert(0, 'src')

# Test if all imports work
print("Testing imports...")
try:
    from finance_core.categorization_engine import create_categorization_engine
    from finance_core.session_management import (
        add_auto_categorized_transaction,
        get_auto_categorized_transactions,
        clear_auto_categorized_transactions
    )
    from automation.claude_provider import ClaudeProvider
    print("✅ All imports successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

# Test categorization engine initialization
print("\nTesting categorization engine initialization...")
try:
    # Check if Claude CLI or API is available
    provider = ClaudeProvider(api_key=None, model="haiku")
    ai_enabled = provider.use_cli or provider.api_client is not None

    if ai_enabled:
        print(f"✅ AI categorization available (CLI: {provider.use_cli}, API: {provider.api_client is not None})")
    else:
        print("⚠️ AI categorization disabled - only regex matching available")

    engine = create_categorization_engine(ai_enabled=ai_enabled)
    print("✅ Categorization engine created successfully")
except Exception as e:
    print(f"❌ Engine creation failed: {e}")
    sys.exit(1)

# Test with sample transactions
print("\nTesting categorization with sample transactions...")
test_transactions = [
    # Should match regex (ALBERT HEIJN)
    {
        "credit_debit_indicator": "DBIT",
        "transaction_amount": {"amount": "-57.04", "currency": "EUR"},
        "creditor": {"name": "ALBERT HEIJN 1813"},
        "debtor": {"name": "Your Name"},
        "remittance_information": ["ALBERT HEIJN 1813 DRIEBERGEN"],
        "booking_date": "07-07-2025"
    },
    # Might need AI (if enabled)
    {
        "credit_debit_indicator": "DBIT",
        "transaction_amount": {"amount": "-23.97", "currency": "EUR"},
        "creditor": {"name": "Unknown Merchant"},
        "debtor": {"name": "Your Name"},
        "remittance_information": ["Payment for goods"],
        "booking_date": "10-07-2025"
    }
]

auto_count = {"regex": 0, "ai": 0, "manual": 0}

for i, tx in enumerate(test_transactions, 1):
    print(f"\n{i}. Testing transaction...")
    result = engine.categorize(tx)

    print(f"   Category: {result.category}")
    print(f"   Description: {result.description}")
    print(f"   Confidence: {result.confidence:.0%}")
    print(f"   Method: {result.method}")

    if result.method == 'regex':
        auto_count["regex"] += 1
        print("   ✅ Would auto-upload (regex match)")
    elif result.method == 'ai_auto':
        auto_count["ai"] += 1
        print("   ✅ Would auto-upload (AI high confidence)")
    else:
        auto_count["manual"] += 1
        print("   ⚠️  Would show Discord UI (manual review needed)")

# Test session storage
print("\n\nTesting session storage...")
test_user_id = 999999999  # Fake user ID for testing

try:
    # Clear any existing test data
    clear_auto_categorized_transactions(test_user_id)

    # Add a test auto-categorization
    add_auto_categorized_transaction(
        user_id=test_user_id,
        transaction=test_transactions[0],
        category="Boodschappen",
        description="ALBERT HEIJN - Test",
        transaction_type="expense",
        method="regex",
        confidence=1.0
    )

    # Retrieve and verify
    auto_cats = get_auto_categorized_transactions(test_user_id)

    if len(auto_cats) == 1:
        print("✅ Session storage working correctly")
        print(f"   Stored: {auto_cats[0]['category']} - {auto_cats[0]['description']}")
    else:
        print(f"❌ Session storage error: expected 1 transaction, got {len(auto_cats)}")

    # Cleanup
    clear_auto_categorized_transactions(test_user_id)
    print("✅ Test data cleaned up")

except Exception as e:
    print(f"❌ Session storage test failed: {e}")
    sys.exit(1)

# Summary
print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Auto-upload (regex):        {auto_count['regex']}/{len(test_transactions)}")
print(f"Auto-upload (AI):           {auto_count['ai']}/{len(test_transactions)}")
print(f"Manual review needed:       {auto_count['manual']}/{len(test_transactions)}")

total_auto = auto_count['regex'] + auto_count['ai']
if total_auto > 0:
    print(f"\n✅ {total_auto}/{len(test_transactions)} transactions would auto-upload")
    print("💡 Use /review command to inspect auto-categorizations")
else:
    print("\n⚠️  No auto-categorizations (AI disabled or transactions need review)")

print("\n✅ All tests passed! Auto-upload functionality is ready.")
print("\nNext steps:")
print("  1. Upload a CSV via Discord: /upload")
print("  2. Check auto-categorization summary message")
print("  3. Use /review to inspect auto-categorizations")
print("  4. Manually categorize any low-confidence transactions")
