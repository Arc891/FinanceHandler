"""
Tests for Phase 3 step 2a: AI chunks run in parallel, the run budget becomes
a deadline, a cancelled CLI call kills its process, and a C-id relationship
annotates the regex row it names.

The chunks never saw each other's rows, so running them together must give
exactly the sequential result; the fakes finish chunks out of order to prove
results are placed by position, not by completion. All rows are synthetic.
"""

import asyncio
import json
import re
import time

import pytest

from automation.ai_categorizer import ClaudeCategorizer
from automation.claude_provider import ClaudeProvider
from finance_core import categorization_engine as ce
from finance_core.categorization_engine import CategorizationEngine
from fakes import expense_tx

T_ID = re.compile(r"^\| (T\d+) \|", re.M)


def raw(tx):
    return {k: v for k, v in tx.items() if k not in ("description", "category")}


def unmatched_rows(n):
    """Rows no regex rule matches, each with its own counterparty."""
    return [raw(expense_tx(name=f"Onbekend {i}", rem=f"ref {i}", seq=str(i)))
            for i in range(1, n + 1)]


class ChunkProvider:
    """Answers a batch prompt for exactly the T-ids it contains.

    delay(first_tid_number) sets how long a chunk takes; fail(first) makes
    a chunk raise. Records the peak number of calls in flight and which
    chunks were cancelled.
    """

    def __init__(self, delay=lambda first: 0.0, fail=lambda first: False):
        self.delay, self.fail = delay, fail
        self.in_flight = self.peak = self.calls = 0
        self.cancelled = []

    async def complete(self, prompt, max_tokens=0, temperature=0.0):
        ids = T_ID.findall(prompt)
        first = int(ids[0][1:])
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay(first))
            if self.fail(first):
                raise RuntimeError("chunk failed")
            return json.dumps({"transactions": [
                {"id": tid, "category": f"cat-{tid}", "description": f"d {tid}",
                 "confidence": "high"} for tid in ids]})
        except asyncio.CancelledError:
            self.cancelled.append(first)
            raise
        finally:
            self.in_flight -= 1


def categorizer(provider):
    cat = ClaudeCategorizer.__new__(ClaudeCategorizer)
    cat.provider, cat.model = provider, "sonnet"
    return cat


async def run_batch(cat, rows, **kwargs):
    expense, income = ce.ai_category_options()
    return await cat.categorize_batch(
        transactions_to_categorize=rows, precategorized_transactions=[],
        expense_categories=expense, income_categories=income,
        example_rules={}, **kwargs)


def categories(results):
    return [r[0] if r else None for r in results]


# ── ClaudeCategorizer.categorize_batch ──────────────────────────────────────

async def test_out_of_order_chunks_land_in_input_order():
    rows = unmatched_rows(100)                 # 40 + 40 + 20
    provider = ChunkProvider(delay=lambda first: 0.06 if first == 1 else
                             0.03 if first == 41 else 0.0)
    results = await run_batch(categorizer(provider), rows, max_parallel=3)
    assert provider.calls == 3
    assert categories(results) == [f"cat-T{i}" for i in range(1, 101)]


async def test_parallel_result_equals_sequential_result():
    rows = unmatched_rows(100)
    parallel = await run_batch(categorizer(ChunkProvider()), rows,
                               max_parallel=3)
    sequential = await run_batch(categorizer(ChunkProvider()), rows,
                                 max_parallel=1)
    assert parallel == sequential


async def test_chunks_actually_overlap():
    provider = ChunkProvider(delay=lambda first: 0.05)
    await run_batch(categorizer(provider), unmatched_rows(100), max_parallel=3)
    assert provider.peak == 3


@pytest.mark.parametrize("limit", [1, 2])
async def test_in_flight_calls_never_exceed_the_limit(limit):
    provider = ChunkProvider(delay=lambda first: 0.02)
    await run_batch(categorizer(provider), unmatched_rows(100),
                    max_parallel=limit)
    assert provider.peak == limit


async def test_one_failing_chunk_leaves_only_its_own_rows_none():
    provider = ChunkProvider(fail=lambda first: first == 41)
    results = await run_batch(categorizer(provider), unmatched_rows(100),
                              max_parallel=3)
    got = categories(results)
    assert got[:40] == [f"cat-T{i}" for i in range(1, 41)]
    assert got[40:80] == [None] * 40
    assert got[80:] == [f"cat-T{i}" for i in range(81, 101)]


async def test_deadline_cancels_the_unfinished_chunks():
    provider = ChunkProvider(delay=lambda first: 0.0 if first == 1 else 30.0)
    started = time.monotonic()
    results = await run_batch(categorizer(provider), unmatched_rows(100),
                              max_parallel=3, deadline=started + 0.2)
    assert time.monotonic() - started < 5
    got = categories(results)
    assert got[:40] == [f"cat-T{i}" for i in range(1, 41)]
    assert got[40:] == [None] * 60
    assert sorted(provider.cancelled) == [41, 81]
    assert provider.in_flight == 0


async def test_deadline_already_passed_makes_no_call():
    provider = ChunkProvider()
    results = await run_batch(categorizer(provider), unmatched_rows(5),
                              deadline=time.monotonic() - 1)
    assert provider.calls == 0
    assert results == [None] * 5


# ── CategorizationEngine.batch_categorize ───────────────────────────────────

class EngineAI:
    """A categoriser whose batch fails for every row, counting fallbacks."""

    def __init__(self, batch=None):
        self.batch = batch
        self.batch_kwargs = None
        self.per_row_calls = 0

    async def categorize_batch(self, transactions_to_categorize,
                               precategorized_transactions, expense_categories,
                               income_categories, example_rules, **kwargs):
        self.batch_kwargs = kwargs
        if self.batch:
            return self.batch(transactions_to_categorize)
        return [None] * len(transactions_to_categorize)

    async def categorize_transaction(self, transaction, expense_categories,
                                     income_categories, example_rules):
        self.per_row_calls += 1
        return "Ander", "iets", 0.9


def engine_with(ai, **kwargs):
    return CategorizationEngine(ai_categorizer=ai, ai_enabled=True, **kwargs)


async def test_fallback_stops_at_the_limit():
    ai = EngineAI()
    results = await engine_with(ai).batch_categorize(
        unmatched_rows(15), fallback_limit=10)
    assert ai.per_row_calls == 10
    assert [r.method for r in results].count("none") == 5


async def test_fallback_limit_defaults_to_config(monkeypatch):
    monkeypatch.setattr(ce, "setting", lambda name, default=None: (
        3 if name == "AI_PER_TX_FALLBACK_LIMIT" else default))
    ai = EngineAI()
    await engine_with(ai).batch_categorize(unmatched_rows(8))
    assert ai.per_row_calls == 3


async def test_no_fallback_after_the_deadline():
    ai = EngineAI()
    results = await engine_with(ai).batch_categorize(
        unmatched_rows(5), deadline=time.monotonic() - 1, fallback_limit=10)
    assert ai.per_row_calls == 0
    assert {r.method for r in results} == {"none"}


async def test_engine_passes_deadline_and_parallelism(monkeypatch):
    monkeypatch.setattr(ce, "setting", lambda name, default=None: (
        2 if name == "AI_MAX_PARALLEL_CHUNKS" else default))
    ai = EngineAI(batch=lambda txs: [("Ander", "x", 0.9, None)] * len(txs))
    deadline = time.monotonic() + 60
    await engine_with(ai).batch_categorize(unmatched_rows(2),
                                           deadline=deadline)
    assert ai.batch_kwargs == {"deadline": deadline, "max_parallel": 2}


async def test_c_id_annotates_the_regex_row_it_names():
    """C2 is the second regex-matched row, not the second row overall."""
    rows = [raw(expense_tx(name="PICNIC", seq="1")),
            raw(expense_tx(name="Onbekend", rem="x", seq="2")),
            raw(expense_tx(name="Vitens", seq="3"))]
    ai = EngineAI(batch=lambda txs: [(
        "Ander", "iets", 0.9,
        {"linked_to": ["C2"], "description_suffix": "(voor water)"})])
    results = await engine_with(ai).batch_categorize(rows)
    assert results[2].method == "regex"
    assert results[2].description_suffix == "(voor water)"
    assert results[0].description_suffix is None


async def test_c_id_out_of_range_is_ignored():
    rows = [raw(expense_tx(name="PICNIC", seq="1")),
            raw(expense_tx(name="Onbekend", rem="x", seq="2"))]
    ai = EngineAI(batch=lambda txs: [(
        "Ander", "iets", 0.9, {"linked_to": ["C7", "Cx"],
                               "description_suffix": "(s)"})])
    results = await engine_with(ai).batch_categorize(rows)
    assert results[0].description_suffix is None


# ── ClaudeProvider: a cancelled CLI call kills its process ──────────────────

class HangingProcess:
    def __init__(self):
        self.killed = False
        self.waited = False
        self.returncode = None

    async def communicate(self):
        await asyncio.sleep(3600)

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        return -9


async def test_cancelled_cli_call_kills_its_process(monkeypatch):
    process = HangingProcess()

    async def fake_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    provider = ClaudeProvider.__new__(ClaudeProvider)
    provider.model, provider.use_cli, provider.api_client = "sonnet", True, None

    task = asyncio.create_task(provider.complete("prompt"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited


async def test_explicit_parallelism_overrides_config(monkeypatch):
    monkeypatch.setattr(ce, "setting", lambda name, default=None: (
        2 if name == "AI_MAX_PARALLEL_CHUNKS" else default))
    ai = EngineAI(batch=lambda txs: [("Ander", "x", 0.9, None)] * len(txs))
    await engine_with(ai).batch_categorize(unmatched_rows(2), max_parallel=1)
    assert ai.batch_kwargs["max_parallel"] == 1
