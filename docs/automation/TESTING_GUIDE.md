# Testing Guide - AI Categorization (Phase 2)

**Last Updated**: 2025-12-16

## Table of Contents

1. [Quick Start](#quick-start)
2. [Privacy & Anonymization](#privacy--anonymization)
3. [Test Suite Overview](#test-suite-overview)
4. [Manual Testing](#manual-testing)
5. [Testing with Real Data](#testing-with-real-data)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

```bash
# 1. Install dependencies
pip install -r requirements.txt

# This includes:
# - anthropic>=0.8.0 (Claude API SDK)
# - All existing dependencies
```

### Run Automated Tests

```bash
# Test without API key (regex + anonymization only)
python scripts/test_ai_categorization.py

# Test with AI (requires API key)
export CLAUDE_API_KEY="sk-ant-..."
python scripts/test_ai_categorization.py
```

### Expected Output

```
================================================================================
  AI Categorization Test Suite - Phase 2
================================================================================

Test 1: Regex-Only Categorization
  ✅ JUMBO supermarket → Boodschappen
  ✅ Greenwheels → Auto/vervoer

Test 2: Data Anonymization & Privacy Protection
  ✅ Removed: 'NL91ABNA0417164300'
  ✅ Removed: '123456789'
  ✅ Kept: 'JUMBO'

Test 3: AI Categorization (requires CLAUDE_API_KEY)
  ✅ Coffee shop → Snacken (confidence: 0.65)
  ✅ Netflix → Abonnementen (confidence: 0.90)

Test 4: Unified Engine
  📊 Statistics:
     Regex matched: 3/7
     AI auto-approved: 2/7
     AI manual review needed: 2/7

✅ All tests passed successfully!
✅ Privacy protection verified - safe to use with real data
```

---

## Privacy & Anonymization

### What is Anonymized

**REMOVED before sending to AI**:
- ✅ IBANs (NL12BANK1234567890)
- ✅ Personal names (e.g., "Jan de Vries", "Marie Schmidt")
- ✅ Reference numbers (e.g., "Referentie: 123456789")
- ✅ Account identifiers (e.g., "Kenmerk: PERS-2025-001")
- ✅ Long numeric sequences that could be personal IDs

**KEPT for categorization**:
- ✅ Merchant names (e.g., "JUMBO", "Netflix", "Greenwheels")
- ✅ Business names with B.V./N.V. (e.g., "Software Solutions B.V.")
- ✅ Transaction amounts (numerical only, no account info)
- ✅ Transaction descriptions (sanitized, no personal references)
- ✅ Dates (just the date, no time or account info)

### Anonymization Examples

**Before Anonymization**:
```json
{
  "creditor": {"name": "Jan de Vries"},
  "remittance_information": ["NL91ABNA0417164300 Referentie: 123456789"]
}
```

**After Anonymization**:
```json
{
  "creditor": "Private Person",
  "remittance_information": "[IBAN] [REF]"
}
```

**Business Transaction (kept)**:
```json
{
  "creditor": "JUMBO Supermarkt",
  "remittance_information": "Betaling JUMBO Driebergen"
}
```
→ Stays intact (merchant name needed for categorization)

### Verify Anonymization

Run the anonymization test:

```bash
python scripts/test_ai_categorization.py
```

Look for **TEST 4: Data Anonymization** section. It should show:
- ✅ All sensitive data removed
- ✅ Merchant names preserved
- ✅ No IBANs, personal names, or references in output

---

## Test Suite Overview

### Test 1: Regex-Only Categorization

**Purpose**: Verify existing regex rules still work

**No API Key Required**: ✅

**What it tests**:
- JUMBO → Boodschappen
- Greenwheels → Auto/vervoer
- Salary payments → Salaris

**Expected**: 100% confidence (regex always returns 1.0)

### Test 2: Data Anonymization

**Purpose**: Verify privacy protection

**No API Key Required**: ✅

**What it tests**:
- IBANs removed from remittance info
- Personal names replaced with "Private Person"
- Reference numbers replaced with [REF]
- Merchant names preserved
- Business names (B.V., N.V.) preserved

**Expected**: All sensitive data removed, merchant data intact

### Test 3: AI Categorization

**Purpose**: Test Claude API integration

**Requires API Key**: ✅

**What it tests**:
- Unknown coffee shop → categorized (e.g., Snacken)
- Netflix → Abonnementen
- Unknown restaurant → categorized (e.g., Dates/uitjes)
- Confidence scoring (high/medium/low)

**Expected**: Reasonable categories with appropriate confidence

### Test 4: Unified Engine

**Purpose**: Test complete pipeline (regex → AI)

**Requires API Key**: ✅

**What it tests**:
- Regex matches processed first (confidence: 1.0)
- Unmatched transactions go to AI
- Confidence threshold applied (0.75)
- Batch statistics accurate

**Expected**: Mix of regex and AI categorizations

---

## Manual Testing

### Test Individual Transactions

Create a Python script:

```python
import sys
sys.path.insert(0, 'src')

from finance_core.categorization_engine import create_categorization_engine

# Create engine
engine = create_categorization_engine(
    claude_api_key="sk-ant-...",  # Your key
    ai_enabled=True,
    ai_confidence_threshold=0.75
)

# Test transaction
transaction = {
    "credit_debit_indicator": "DBIT",
    "transaction_amount": {"amount": "-12.50", "currency": "EUR"},
    "creditor": {"name": "Test Merchant"},
    "debtor": {"name": "Your Name"},
    "remittance_information": ["Test payment"],
    "booking_date": "2025-01-15"
}

result = engine.categorize(transaction)

print(f"Category: {result.category}")
print(f"Description: {result.description}")
print(f"Confidence: {result.confidence}")
print(f"Method: {result.method}")
```

### Test Anonymization Manually

```python
import sys
sys.path.insert(0, 'src')

from automation.data_anonymizer import anonymize_for_ai

# Your transaction with sensitive data
transaction = {
    "credit_debit_indicator": "DBIT",
    "transaction_amount": {"amount": "-45.50", "currency": "EUR"},
    "creditor": {"name": "Jan de Vries"},
    "remittance_information": ["NL91ABNA0417164300 Payment"],
    "booking_date": "2025-01-15"
}

# Anonymize
anonymized = anonymize_for_ai(transaction)

print("Original:", transaction)
print("Anonymized:", anonymized)

# Verify: Should NOT contain "Jan de Vries" or "NL91ABNA0417164300"
```

---

## Testing with Real Data

### Step 1: Export Test CSV from ASN Bank

1. Log into ASN Bank
2. Go to "Transactions"
3. Export last 7 days as CSV
4. Save to `test_transactions.csv`

### Step 2: Test Anonymization with Real Data

```python
import sys
sys.path.insert(0, 'src')

from finance_core.csv_helper import load_transactions_from_csv
from automation.data_anonymizer import anonymize_for_ai

# Load real transactions
transactions = load_transactions_from_csv('test_transactions.csv')

# Test first transaction
tx = transactions[0]
print("Original transaction:")
print(f"  Creditor: {tx.get('creditor', {}).get('name', 'N/A')}")
print(f"  Remittance: {tx.get('remittance_information', ['N/A'])[0][:50]}...")

# Anonymize
anonymized = anonymize_for_ai(tx)
print("\nAnonymized transaction:")
print(f"  Creditor: {anonymized.get('creditor', 'N/A')}")
print(f"  Remittance: {anonymized.get('remittance_information', 'N/A')[:50]}...")

# VERIFY: Check that no personal data remains
```

### Step 3: Test Categorization with Real Data

**IMPORTANT**: Only proceed if anonymization test passed!

```python
import sys
sys.path.insert(0, 'src')

from finance_core.csv_helper import load_transactions_from_csv
from finance_core.categorization_engine import create_categorization_engine

# Load transactions
transactions = load_transactions_from_csv('test_transactions.csv')

# Create engine
engine = create_categorization_engine(
    claude_api_key="sk-ant-...",
    ai_enabled=True,
    ai_confidence_threshold=0.75
)

# Categorize all
results = engine.batch_categorize(transactions)

# Show statistics
regex_count = sum(1 for r in results if r.method == 'regex')
ai_auto = sum(1 for r in results if r.method == 'ai_auto')
ai_manual = sum(1 for r in results if r.method == 'ai_manual_needed')

print(f"\nResults:")
print(f"  Regex matched: {regex_count}/{len(results)}")
print(f"  AI auto-approved: {ai_auto}/{len(results)}")
print(f"  Manual review needed: {ai_manual}/{len(results)}")

# Show first few results
print("\nSample categorizations:")
for i, result in enumerate(results[:5]):
    print(f"\n{i+1}. {result.category}")
    print(f"   Description: {result.description}")
    print(f"   Confidence: {result.confidence:.2f}")
    print(f"   Method: {result.method}")
```

### Step 4: Review AI Suggestions

Review the categorizations to ensure:
- ✅ Categories make sense
- ✅ Descriptions are accurate
- ✅ Confidence scores are reasonable
- ✅ No personal data in logs

---

## Troubleshooting

### Issue: "CLAUDE_API_KEY not found"

**Solution**:
```bash
export CLAUDE_API_KEY="sk-ant-..."

# Or add to .env file
echo 'CLAUDE_API_KEY=sk-ant-...' >> .env
```

### Issue: "anthropic module not found"

**Solution**:
```bash
pip install anthropic>=0.8.0
```

### Issue: AI returns low confidence for everything

**Possible causes**:
1. Poor transaction descriptions
2. Unclear merchant names
3. Categories don't match transaction types

**Solution**:
- Review AI_CATEGORIZATION.md for prompt tuning
- Check if categories in constants.py match your needs
- Consider lowering threshold to 0.60-0.70 for testing

### Issue: Sensitive data not being removed

**Solution**:
1. Run anonymization test: `python scripts/test_ai_categorization.py`
2. Check TEST 4 output for failures
3. Review `data_anonymizer.py` patterns
4. Add new patterns if needed

### Issue: Known merchants being anonymized

**Solution**:
Edit `src/automation/data_anonymizer.py`:

```python
KNOWN_MERCHANTS = [
    # Add your merchants here
    'YOUR_MERCHANT_NAME',
    'ANOTHER_MERCHANT',
]
```

### Issue: High API costs

**Check**:
1. How many transactions are being sent to AI?
2. Are regex rules matching correctly first?
3. Review API usage in Anthropic console

**Solution**:
- Improve regex rules to catch more transactions
- Increase confidence threshold to reduce API calls
- Use batch processing instead of individual calls

---

## Test Checklist

Before enabling AI categorization in production:

- [ ] Run full test suite: `python scripts/test_ai_categorization.py`
- [ ] All anonymization tests pass
- [ ] Test with sample real transactions
- [ ] Verify no personal data in anonymized output
- [ ] Review AI categorization accuracy (>80% correct)
- [ ] Check API costs are acceptable
- [ ] Test batch processing performance
- [ ] Review confidence threshold (0.75 recommended)
- [ ] Enable in config: `AI_CATEGORIZATION_ENABLED = True`

---

## Next Steps

After testing:

1. **Enable in production**:
   ```python
   # In config_settings.py
   AI_CATEGORIZATION_ENABLED = True
   ```

2. **Monitor performance**:
   - Check categorization accuracy
   - Monitor API costs
   - Review confidence scores

3. **Tune as needed**:
   - Adjust confidence threshold
   - Add more regex rules
   - Update merchant patterns

4. **Proceed to Phase 3**:
   - Discord approval UI for low-confidence transactions
   - Integration with existing bot commands
   - End-to-end automation

---

**Remember**: All data is anonymized before being sent to the API. Review the anonymization tests carefully to ensure your privacy is protected!
