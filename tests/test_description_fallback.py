"""
Tests for graceful description fallback and the auto-vs-review guard.

Background: card/POS payments leave creditor/debtor name empty (the merchant
is in the remittance), which previously produced descriptions like
"Unknown - McDonald's Geldermalsen". We now:
  - drop the counterparty prefix when there is no real name, and
  - route transactions with no usable description to manual review instead of
    auto-uploading them with a junk label.

Run: python -m unittest tests.test_description_fallback  (from project root)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from automation.ai_categorizer import ClaudeCategorizer  # noqa: E402
from finance_core.categorization_engine import CategorizationEngine  # noqa: E402


class TestBuildLocalDescription(unittest.TestCase):
    """ClaudeCategorizer._build_local_description graceful fallback."""

    build = staticmethod(ClaudeCategorizer._build_local_description)

    def test_empty_counterparty_returns_ai_description_alone(self):
        # The merchant is already in the AI description.
        self.assertEqual(
            self.build("", "McDonald's Geldermalsen", "Snacken"),
            "McDonald's Geldermalsen")

    def test_unknown_sentinel_treated_as_no_counterparty(self):
        # Legacy 'Unknown' sentinel must not be prepended.
        out = self.build("Unknown", "Lunch Bagels & Beans Maastricht", "Dates")
        self.assertEqual(out, "Lunch Bagels & Beans Maastricht")
        self.assertNotIn("Unknown", out)

    def test_real_counterparty_prepended_when_absent_from_desc(self):
        self.assertEqual(
            self.build("Jan de Vries", "Payment received", "Ander"),
            "Jan de Vries - Payment received")

    def test_counterparty_already_in_desc_kept_as_is(self):
        self.assertEqual(
            self.build("Picnic", "Picnic inkopen", "Boodschappen"),
            "Picnic inkopen")

    def test_private_person_replaced_with_real_counterparty(self):
        self.assertEqual(
            self.build("Oma", "Gift from Private Person", "Gift"),
            "Gift from Oma")

    def test_private_person_stripped_when_no_counterparty(self):
        # No real name to restore -> drop placeholder, no dangling separators.
        out = self.build("", "Private Person - Gezellig weekend", "Dates")
        self.assertEqual(out, "Gezellig weekend")
        self.assertNotIn("Private Person", out)
        self.assertFalse(out.startswith("-"))

    def test_no_counterparty_and_no_desc_returns_empty(self):
        # Nothing usable -> empty, so the caller routes it to manual review.
        self.assertEqual(self.build("", "", "Boodschappen"), "")
        self.assertEqual(self.build("Unknown", "", "Boodschappen"), "")

    def test_counterparty_only_when_desc_empty(self):
        self.assertEqual(
            self.build("Albert Heijn", "", "Boodschappen"), "Albert Heijn")


class TestDecideMethod(unittest.TestCase):
    """CategorizationEngine._decide_method: blank description -> review."""

    def setUp(self):
        self.engine = CategorizationEngine(ai_confidence_threshold=0.75)

    def test_high_confidence_with_description_is_auto(self):
        self.assertEqual(
            self.engine._decide_method(0.9, "Boodschappen"), "ai_auto")

    def test_high_confidence_blank_description_needs_review(self):
        self.assertEqual(
            self.engine._decide_method(0.9, ""), "ai_manual_needed")

    def test_high_confidence_whitespace_description_needs_review(self):
        self.assertEqual(
            self.engine._decide_method(0.9, "   "), "ai_manual_needed")

    def test_low_confidence_needs_review(self):
        self.assertEqual(
            self.engine._decide_method(0.6, "Boodschappen"), "ai_manual_needed")


if __name__ == "__main__":
    unittest.main()
