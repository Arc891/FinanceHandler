"""
Tests for the pot hint (step 2 of the rule work): a purchase no rule covers
that exactly equals one transfer in from the savings account within 7 days
gets a note in the AI prompt. It is context, never a category: a covered
purchase is not always booked Uit spaarpotje (bills stay Rekeningen). A
purchase two transfers could explain, or a transfer two purchases could
use up, gets no note. All rows and account numbers are synthetic.
"""

import asyncio

from automation.ai_categorizer import ClaudeCategorizer
from finance_core.categorization_engine import CategorizationEngine
from finance_core.pot_links import POT_WINDOW_DAYS, pot_hints
from fakes import expense_tx, income_tx

SAVINGS = "NL99SAVE0000000001"


def buy(date, amount, name="Webshop"):
    t = expense_tx(date_str=date, amount=f"-{amount}", name=name, rem="bestelling")
    return {k: v for k, v in t.items() if k not in ("description", "category")}


def cover(date, amount, iban=SAVINGS):
    t = income_tx(date_str=date, amount=amount, name="Spaarrekening", rem="naar potje")
    t = {k: v for k, v in t.items() if k not in ("description", "category")}
    t["counterparty_iban"] = iban
    return t


def hints(txs, candidates=None):
    candidates = range(len(txs)) if candidates is None else candidates
    return pot_hints(txs, candidates, {SAVINGS})


def test_a_purchase_one_transfer_covers_exactly_gets_a_hint():
    got = hints([buy("09-03-2025", "45.00"), cover("11-03-2025", "45.00")])
    assert got == {0: "same amount as a transfer in from the savings account on 11-03-2025"}


def test_a_transfer_from_another_account_gives_no_hint():
    assert hints([buy("09-03-2025", "45.00"), cover("11-03-2025", "45.00", iban="NL00OTHR0000000000")]) == {}


def test_a_transfer_beyond_the_window_gives_no_hint():
    assert POT_WINDOW_DAYS == 7
    assert hints([buy("01-03-2025", "45.00"), cover("09-03-2025", "45.00")]) == {}


def test_a_different_amount_gives_no_hint():
    assert hints([buy("09-03-2025", "45.00"), cover("10-03-2025", "45.01")]) == {}


def test_two_purchases_one_transfer_could_cover_get_no_hint():
    assert hints([buy("09-03-2025", "45.00"), buy("10-03-2025", "45.00", name="Other"),
                  cover("11-03-2025", "45.00")]) == {}


def test_a_purchase_two_transfers_could_cover_gets_no_hint():
    assert hints([cover("08-03-2025", "45.00"), buy("09-03-2025", "45.00"), cover("11-03-2025", "45.00")]) == {}


def test_only_candidate_rows_get_a_hint():
    """Rows a rule already categorised are not sent to the AI."""
    assert hints([buy("09-03-2025", "45.00"), cover("11-03-2025", "45.00")], candidates=[1]) == {}


def test_the_hint_reaches_the_prompt_on_its_own_row():
    ai = ClaudeCategorizer.__new__(ClaudeCategorizer)
    orig = [{**buy("09-03-2025", "45.00"), "pot_hint": "same amount as a transfer in"},
            buy("10-03-2025", "7.00")]
    anon = [{"booking_date": t["booking_date"], "credit_debit_indicator": "DBIT",
             "transaction_amount": float(t["transaction_amount"]["amount"][1:]),
             "creditor": "Merchant", "remittance_information": "bestelling"} for t in orig]
    prompt = ai._build_batch_prompt(anon, [], [], {"Uit spaarpotje": ""}, {}, {}, ["T1", "T2"],
                                    orig_to_categorize=orig)
    t1 = next(line for line in prompt.splitlines() if line.startswith("| T1 "))
    t2 = next(line for line in prompt.splitlines() if line.startswith("| T2 "))
    assert "same amount as a transfer in" in t1 and "same amount" not in t2
    assert "Hint" in prompt


class RecordingAI:
    def __init__(self):
        self.sent = None

    async def categorize_batch(self, transactions_to_categorize, **kwargs):
        self.sent = transactions_to_categorize
        return [("Uit spaarpotje", "Webshop", 0.9, None)] * len(transactions_to_categorize)


def test_the_engine_hands_the_ai_the_hint_without_changing_the_row(monkeypatch):
    monkeypatch.setattr("finance_core.tx_features.account_roles", lambda: {"savings": [SAVINGS]})
    ai = RecordingAI()
    engine = CategorizationEngine(ai_categorizer=ai, ai_enabled=True)
    purchase = buy("09-03-2025", "45.00")
    txs = [purchase, cover("11-03-2025", "45.00")]
    asyncio.run(engine.batch_categorize(txs))
    sent = {t["booking_date"]: t.get("pot_hint") for t in ai.sent}
    assert sent["09-03-2025"].endswith("on 11-03-2025")
    assert "pot_hint" not in purchase
