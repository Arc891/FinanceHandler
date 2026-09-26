"""
Phase 3 step 5: the review UI and its queues are gone (plan 4.8).

The plan's exit check, as a test, so nothing brings the modules back:
`grep -rn "background_upload|pending_transactions|transaction_prompt|
session_management|DUMMY_CACHED" src` must find nothing. Mentions in
docstrings and comments that name a module as the origin of moved code are
not imports, so only code lines count.
"""

import importlib.util
import os
import re

from constants import ExpenseCategory, IncomeCategory

SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
GONE = ("background_upload", "pending_transactions", "transaction_prompt",
        "session_management", "cached_transactions_view", "discord_notifier",
        "DUMMY_CACHED")
MODULES = ("finance_core.background_upload", "finance_core.pending_transactions",
           "finance_core.session_management", "finance_core.ui")


def code_lines(path):
    """Lines outside docstrings, with trailing comments dropped."""
    text = open(path, encoding="utf-8").read()
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    for line in text.splitlines():
        yield line.split("#", 1)[0]


def test_no_source_line_uses_a_removed_name():
    hits = []
    for folder, _, files in os.walk(SRC):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                hits += [f"{os.path.relpath(path, SRC)}: {line.strip()}"
                         for line in code_lines(path)
                         if any(g in line for g in GONE)]
    assert hits == []


def test_the_removed_modules_do_not_import():
    for module in MODULES:
        assert importlib.util.find_spec(module) is None, module


def test_the_cached_placeholder_category_is_gone():
    assert not hasattr(ExpenseCategory, "DUMMY_CACHED")
    assert not hasattr(IncomeCategory, "DUMMY_CACHED")
    assert "CACHED" not in {c.value for c in ExpenseCategory}
    assert "CACHED" not in {c.value for c in IncomeCategory}
