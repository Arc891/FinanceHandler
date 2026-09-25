"""Tests for scripts/time_ai_chunk.py: selection of one AI chunk, and no row content in the output."""

import asyncio
from types import SimpleNamespace

import time_ai_chunk


def rows(n):
    return [{"booking_date": f"{i + 1:02d}-06-2026", "name": f"secret-{i}"} for i in range(n)]


def test_slice_stops_at_the_row_that_fills_the_chunk():
    txs = rows(10)
    matched = lambda tx: int(tx["name"].split("-")[1]) % 2 == 0     # 0, 2, 4 ... match regex
    picked = time_ai_chunk.slice_for_one_chunk(txs, matched, size=3)
    assert picked == txs[:6]                                        # unmatched 1, 3, 5


def test_slice_takes_everything_when_the_file_is_short_of_a_chunk():
    txs = rows(4)
    assert time_ai_chunk.slice_for_one_chunk(txs, lambda tx: False, size=40) == txs


class FakeEngine:
    ai_enabled = True

    def _apply_regex_rules(self, tx):
        return (None, None)

    async def batch_categorize(self, txs):
        return [SimpleNamespace(method="ai_auto", category="secret-category", description="secret")
                for _ in txs]


def test_report_holds_counts_and_time_only():
    lines = []
    asyncio.run(time_ai_chunk.run(rows(5), FakeEngine(), size=40, say=lines.append))
    out = "\n".join(lines)
    assert "secret" not in out
    assert "5 rows" in out and "ai_auto: 5" in out and "seconds" in out
