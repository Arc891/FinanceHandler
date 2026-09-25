"""
No log record from the categorisation path carries a person's name, a
description, a remittance text or an amount -- at any level, DEBUG included.

The bot's logs end up in `docker logs` on the Pi, and the evaluation script
runs the same code over two years of real transactions. Before this test the
anonymiser logged every personal name it replaced, at WARNING. All data here
is synthetic.
"""

import logging

import pytest

from automation.data_anonymizer import anonymize_batch_for_ai, anonymize_for_ai
from finance_core.categorization_engine import CategorizationEngine
from fakes import expense_tx

NAME = "Jolanda Vermeulen"
SINGLE = "Pietje"
DESCRIPTION = "Terugbetaling etentje Jolanda"
REMITTANCE = "Tikkie etentje 3 mei"
AMOUNT = "-47.35"


def raw(tx):
    return {k: v for k, v in tx.items() if k not in ("description", "category")}


def leaked(caplog):
    text = "\n".join(r.getMessage() for r in caplog.records)
    return [s for s in (NAME, "Jolanda", SINGLE, DESCRIPTION, REMITTANCE,
                        "47.35") if s in text]


@pytest.fixture(autouse=True)
def everything(caplog):
    caplog.set_level(logging.DEBUG)


def test_anonymiser_does_not_log_the_names_it_replaces(caplog):
    anonymize_for_ai(raw(expense_tx(name=NAME, amount=AMOUNT, rem=REMITTANCE)))
    anonymize_for_ai(raw(expense_tx(name=SINGLE, amount=AMOUNT, rem=REMITTANCE)))
    anonymize_batch_for_ai([raw(expense_tx(name=NAME, amount=AMOUNT,
                                           rem=REMITTANCE))])
    assert leaked(caplog) == []


async def test_regex_match_is_logged_without_its_description(caplog):
    engine = CategorizationEngine(ai_enabled=False)
    tx = raw(expense_tx(name="Eigen rekening", amount=AMOUNT,
                        rem="Maandelijks spaargeld - Jolanda"))
    result = await engine.categorize(tx)
    assert result.description == "Sparen - Jolanda"
    assert leaked(caplog) == []


class OneRowAI:
    async def categorize_transaction(self, transaction, expense_categories,
                                     income_categories, example_rules):
        return "Dates/uitjes", DESCRIPTION, 0.9

    async def categorize_batch(self, transactions_to_categorize, *args,
                               **kwargs):
        return [("Dates/uitjes", DESCRIPTION, 0.3, None)
                for _ in transactions_to_categorize]


@pytest.mark.parametrize("path", ["single", "batch"])
async def test_ai_decisions_are_logged_without_their_description(caplog, path):
    engine = CategorizationEngine(ai_categorizer=OneRowAI(), ai_enabled=True)
    tx = raw(expense_tx(name=NAME, amount=AMOUNT, rem=REMITTANCE))
    if path == "single":
        await engine.categorize(tx)
    else:
        await engine.batch_categorize([tx])
    assert leaked(caplog) == []


class JsonProvider:
    async def complete(self, prompt, max_tokens=0, temperature=0.0):
        return ('{"category": "Dates/uitjes", "description": "%s", '
                '"confidence": 0.9}' % DESCRIPTION)


async def test_claude_categorizer_per_row_path_logs_no_row_content(caplog):
    from automation.ai_categorizer import ClaudeCategorizer
    from finance_core.categorization_engine import ai_category_options
    cat = ClaudeCategorizer.__new__(ClaudeCategorizer)
    cat.provider, cat.model = JsonProvider(), "sonnet"
    expense, income = ai_category_options()
    await cat.categorize_transaction(
        raw(expense_tx(name=NAME, amount=AMOUNT, rem=REMITTANCE)),
        expense, income, {})
    assert leaked(caplog) == []
