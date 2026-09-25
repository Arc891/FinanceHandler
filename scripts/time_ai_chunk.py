#!/usr/bin/env python3
"""
Time AI categorisation chunks, to size AI_RUN_MAX_MINUTES (plan Phases 2, 3).

Takes the leading slice of an export that holds exactly ``--chunks`` chunks
of rows the regex rules do not match -- what one period sends to the AI, with
the regex-matched rows of the same dates as context -- runs batch_categorize
on it once, and prints counts and elapsed seconds. It never prints amounts,
names, descriptions or categories. Use the anonymised fixture.

Phase 2 timed one chunk on the Pi's image as it was:

    scp scripts/time_ai_chunk.py tests/fixtures/multi_month.csv rp5:/tmp/
    # then, on the Pi:
    docker cp /tmp/time_ai_chunk.py finance-automation-bot:/tmp/
    docker cp /tmp/multi_month.csv finance-automation-bot:/tmp/
    docker exec finance-automation-bot python /tmp/time_ai_chunk.py /tmp/multi_month.csv

To time this branch's parallel chunks (Phase 3 step 2a) inside the same
image, also ship the branch's AI code, without src/config (the image's own
config package stays in use), and point ``--src`` at it:

    git archive --format=tar HEAD src/automation src/finance_core src/constants.py \
        | ssh rp5 'cat > /tmp/branch-src.tar'
    # then, on the Pi:
    docker cp /tmp/branch-src.tar finance-automation-bot:/tmp/
    docker exec finance-automation-bot sh -c 'mkdir -p /tmp/branch && tar -xf /tmp/branch-src.tar -C /tmp/branch'
    docker exec finance-automation-bot python /tmp/time_ai_chunk.py /tmp/multi_month.csv \
        --src /tmp/branch/src --chunks 2 --parallel 1
    # and again with --parallel 3

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


def prepend_src(src):
    """Put a source tree first on sys.path, ahead of the image's /app/src."""
    sys.path.insert(0, src)


async def run(txs, engine, *, size=CHUNK_SIZE, chunks=1, parallel=None, say=print):
    def matched(tx):
        return engine._apply_regex_rules(tx)[0] is not None

    picked = slice_for_one_chunk(txs, matched, size * chunks)
    to_ai = sum(1 for tx in picked if not matched(tx))
    say(f"slice: {len(picked)} rows, {len(picked) - to_ai} regex-matched, {to_ai} to the AI"
        f" (ai_enabled={engine.ai_enabled})")
    kwargs = {} if parallel is None else {"max_parallel": parallel}
    started = time.monotonic()
    results = await engine.batch_categorize(picked, **kwargs)
    elapsed = time.monotonic() - started
    methods = Counter(r.method for r in results)
    say("methods: " + ", ".join(f"{m}: {n}" for m, n in sorted(methods.items())))
    n_chunks = -(-to_ai // size)
    say(f"elapsed: {elapsed:.1f} seconds for {to_ai} AI rows in {n_chunks} chunk(s), "
        f"parallel {parallel if parallel is not None else 'from config'}")
    return elapsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("csv", help="an ASN export; use the anonymised fixture")
    parser.add_argument("--size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--chunks", type=int, default=1,
                        help="how many chunks of AI rows to send in one batch")
    parser.add_argument("--parallel", type=int, default=None,
                        help="chunks in flight at once; default AI_MAX_PARALLEL_CHUNKS")
    parser.add_argument("--src", default=None,
                        help="a source tree to import instead of the image's")
    args = parser.parse_args(argv)
    if args.src:
        prepend_src(args.src)

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
    asyncio.run(run(txs, engine, size=args.size, chunks=args.chunks,
                    parallel=args.parallel))
    return 0


if __name__ == "__main__":
    sys.exit(main())
