#!/usr/bin/env python3
"""
Time one 40-row AI categorisation chunk, to size AI_RUN_MAX_MINUTES (plan Phase 2).

Takes the leading slice of an export that holds exactly one chunk of rows the
regex rules do not match -- what one period sends to the AI, with the
regex-matched rows of the same dates as context -- runs batch_categorize on
it once, and prints counts and elapsed seconds. It never prints amounts,
names, descriptions or categories. Use the anonymised fixture.

Runs on the Pi's current image, whose AI code is identical to this branch:

    scp scripts/time_ai_chunk.py tests/fixtures/multi_month.csv rp5:/tmp/
    # then, on the Pi:
    docker cp /tmp/time_ai_chunk.py finance-automation-bot:/tmp/
    docker cp /tmp/multi_month.csv finance-automation-bot:/tmp/
    docker exec finance-automation-bot python /tmp/time_ai_chunk.py /tmp/multi_month.csv

The input is copied to a temporary directory first, because older csv_helper
versions rewrite their input in place.
"""

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
import time
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for candidate in (os.path.join(PROJECT_ROOT, "src"), "/app/src"):
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)

CHUNK_SIZE = 40          # ai_categorizer.categorize_batch's chunk_size


def slice_for_one_chunk(txs, is_matched, size=CHUNK_SIZE):
    """The shortest leading slice of ``txs`` holding ``size`` regex-unmatched rows."""
    unmatched = 0
    for i, tx in enumerate(txs):
        if not is_matched(tx):
            unmatched += 1
            if unmatched == size:
                return txs[:i + 1]
    return list(txs)


async def run(txs, engine, *, size=CHUNK_SIZE, say=print):
    def matched(tx):
        return engine._apply_regex_rules(tx)[0] is not None

    picked = slice_for_one_chunk(txs, matched, size)
    to_ai = sum(1 for tx in picked if not matched(tx))
    say(f"slice: {len(picked)} rows, {len(picked) - to_ai} regex-matched, {to_ai} to the AI"
        f" (ai_enabled={engine.ai_enabled})")
    started = time.monotonic()
    results = await engine.batch_categorize(picked)
    elapsed = time.monotonic() - started
    methods = Counter(r.method for r in results)
    say("methods: " + ", ".join(f"{m}: {n}" for m, n in sorted(methods.items())))
    say(f"elapsed: {elapsed:.1f} seconds for one chunk of {to_ai}")
    return elapsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("csv", help="an ASN export; use the anonymised fixture")
    parser.add_argument("--size", type=int, default=CHUNK_SIZE)
    args = parser.parse_args(argv)

    import logging
    logging.basicConfig(level=logging.WARNING)

    from finance_core.categorization_engine import create_categorization_engine
    from finance_core.csv_helper import load_transactions_from_csv

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, os.path.basename(args.csv))
        shutil.copy(args.csv, path)
        txs = load_transactions_from_csv(path)
    engine = create_categorization_engine(ai_enabled=True)
    if not engine.ai_enabled:
        print("AI is not enabled here (no Claude CLI or API key); nothing to time.")
        return 1
    asyncio.run(run(txs, engine, size=args.size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
