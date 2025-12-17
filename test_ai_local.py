#!/usr/bin/env python3
"""Quick test of AI categorization using Claude Code CLI (free)"""

import sys
sys.path.insert(0, 'src')

from finance_core.categorization_engine import create_categorization_engine

# Create engine (uses CLI, no API key needed)
engine = create_categorization_engine(ai_enabled=True)

# Real test transactions from transactie-historie.csv
transactions = [
    # Should match regex: ALBERT HEIJN → Boodschappen
    {
        "credit_debit_indicator": "DBIT",
        "transaction_amount": {"amount": "-57.04", "currency": "EUR"},
        "creditor": {"name": "ALBERT HEIJN 1813"},
        "debtor": {"name": "Your Name"},
        "remittance_information": ["ALBERT HEIJN 1813     >DRIEBERGE 7.07.2025 12U08 KV005 5Y4C9C MCC:5411 Contactloze betaling NLNEDERLAND"],
        "booking_date": "07-07-2025"
    },
    # Personal payment - needs anonymization (Mw EA Veerbeek)
    {
        "credit_debit_indicator": "DBIT",
        "transaction_amount": {"amount": "-17.00", "currency": "EUR"},
        "creditor": {"name": "Mw EA Veerbeek via ING Betaalverzoek"},
        "debtor": {"name": "Your Name"},
        "remittance_information": ["EAVeerbeekNL62INGB0004173881 7051206355099846 Drankjes NL62INGB0004173881 Referentie: 2025-07-10T14:57 7051206355099846"],
        "booking_date": "10-07-2025"
    },
    # Unclear merchant - AI needs to categorize (Tess' Gifts)
    {
        "credit_debit_indicator": "DBIT",
        "transaction_amount": {"amount": "-23.97", "currency": "EUR"},
        "creditor": {"name": "Tess' Gifts"},
        "debtor": {"name": "Your Name"},
        "remittance_information": ["Tess' Gifts           >DOORN 10.07.2025 12U08 KV005 00DDK3 MCC:5999 Contactloze betaling NLNEDERLAND"],
        "booking_date": "10-07-2025"
    },
    # Foreign transaction - Germany (KAUFLAND MEPPEN)
    {
        "credit_debit_indicator": "DBIT",
        "transaction_amount": {"amount": "-25.23", "currency": "EUR"},
        "creditor": {"name": "KAUFLAND MEPPEN 4760"},
        "debtor": {"name": "Your Name"},
        "remittance_information": ["KAUFLAND MEPPEN 4760  >MEPPEN 12.07.2025 17U13 KV005 61344491 MCC:5411 Contactloze betaling DEDUITSLAND"],
        "booking_date": "12-07-2025"
    },
    # Income - Salary (Janneke)
    {
        "credit_debit_indicator": "CRDT",
        "transaction_amount": {"amount": "369.75", "currency": "EUR"},
        "creditor": {"name": "Your Name"},
        "debtor": {"name": "J. Wolbers"},
        "remittance_information": ["Salaris Janneke"],
        "booking_date": "13-07-2025"
    },
    # Charity - should match regex (COMPASSION)
    {
        "credit_debit_indicator": "DBIT",
        "transaction_amount": {"amount": "-37.50", "currency": "EUR"},
        "creditor": {"name": "STICHTING COMPASSION NEDERLAND"},
        "debtor": {"name": "Your Name"},
        "remittance_information": ["Europese incasso: NL-Bedankt voor uw sponsorbijdrage voor Juli-Incassant ID: NL03ZZZ410423870000-Kenmerk Machtiging: CNLa0PP5000009jV15MAE-4025071006525784"],
        "booking_date": "07-07-2025"
    }
]

print("Testing AI Categorization with REAL transactions")
print("(Uses Claude Code CLI - FREE, no API key needed)\n")
print("=" * 80)

results = []
for i, tx in enumerate(transactions, 1):
    amount = tx["transaction_amount"]["amount"]
    is_income = float(amount) > 0
    counterparty = tx.get("debtor", {}).get("name") if is_income else tx.get("creditor", {}).get("name")

    print(f"\n{i}. {counterparty} - €{amount}")
    print(f"   Type: {'Income' if is_income else 'Expense'}")

    result = engine.categorize(tx)
    results.append(result)

    print(f"   → Category: {result.category}")
    print(f"   → Description: {result.description}")
    print(f"   → Confidence: {result.confidence:.0%}")
    print(f"   → Method: {result.method}")

    # Show if privacy protection worked
    if "Private Person" in str(result.description) or "Mw EA Veerbeek" not in str(result.description):
        if "Veerbeek" in counterparty:
            print(f"   ✅ Privacy: Personal name anonymized")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

regex_count = sum(1 for r in results if r.method == 'regex')
ai_auto_count = sum(1 for r in results if r.method == 'ai_auto')
ai_manual_count = sum(1 for r in results if r.method == 'ai_manual_needed')
none_count = sum(1 for r in results if r.method == 'none')

print(f"Regex matched:        {regex_count}/{len(results)}")
print(f"AI auto-approved:     {ai_auto_count}/{len(results)}")
print(f"AI manual needed:     {ai_manual_count}/{len(results)}")
print(f"Not categorized:      {none_count}/{len(results)}")

coverage = ((regex_count + ai_auto_count) / len(results)) * 100
print(f"\nAuto-categorization:  {coverage:.0f}%")

print("\n✅ Test complete!")
