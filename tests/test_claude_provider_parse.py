"""
Tests for ClaudeProvider._parse_cli_response.

Regression coverage for the Claude Code CLI changing its
`--output-format json` shape from a single object to an array of messages,
which broke categorization with: 'list' object has no attribute 'get'.

Run: python -m unittest tests.test_claude_provider_parse  (from src/ on path)
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from automation.claude_provider import ClaudeProvider  # noqa: E402


class TestParseCliResponse(unittest.TestCase):

    def test_new_array_format_returns_result(self):
        """Newer CLI: array of messages ending in a type==result object."""
        payload = [
            {"type": "system", "subtype": "init", "session_id": "abc"},
            {"type": "assistant", "message": {"role": "assistant"}},
            {"type": "result", "subtype": "success", "is_error": False,
             "result": "Boodschappen", "total_cost_usd": 0.0123},
        ]
        text, cost = ClaudeProvider._parse_cli_response(json.dumps(payload))
        self.assertEqual(text, "Boodschappen")
        self.assertAlmostEqual(cost, 0.0123)

    def test_old_object_format_still_works(self):
        """Older CLI: single object. Must remain backward-compatible."""
        payload = {"is_error": False, "result": "Salaris",
                   "total_cost_usd": 0.05}
        text, cost = ClaudeProvider._parse_cli_response(json.dumps(payload))
        self.assertEqual(text, "Salaris")
        self.assertAlmostEqual(cost, 0.05)

    def test_array_error_result_raises(self):
        """An is_error result in array form must raise, not return text."""
        payload = [
            {"type": "system", "subtype": "init"},
            {"type": "result", "is_error": True,
             "result": "rate limit exceeded"},
        ]
        with self.assertRaises(RuntimeError) as ctx:
            ClaudeProvider._parse_cli_response(json.dumps(payload))
        self.assertIn("rate limit", str(ctx.exception))

    def test_array_without_result_falls_back_to_last_dict(self):
        """No explicit result object -> use the last dict in the stream."""
        payload = [
            {"type": "system"},
            {"type": "assistant", "is_error": False, "result": "Ander"},
        ]
        text, _ = ClaudeProvider._parse_cli_response(json.dumps(payload))
        self.assertEqual(text, "Ander")

    def test_missing_result_key_returns_empty(self):
        payload = [{"type": "result", "is_error": False}]
        text, cost = ClaudeProvider._parse_cli_response(json.dumps(payload))
        self.assertEqual(text, "")
        self.assertEqual(cost, 0)

    def test_unexpected_type_raises(self):
        with self.assertRaises(RuntimeError):
            ClaudeProvider._parse_cli_response(json.dumps("just a string"))

    def test_malformed_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            ClaudeProvider._parse_cli_response("{not valid json")


if __name__ == "__main__":
    unittest.main()
