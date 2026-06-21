#!/usr/bin/env python3
"""
Retroactively re-categorize transactions stuck in the pending-approval queue.

When AI categorization fails (e.g. CLI output-format change), transactions that
needed AI fall through to manual review. After the AI path is fixed, this script
re-runs categorization on those pending items:

  - confidence >= threshold  -> upload to the configured month sheet and remove
                                from the pending queue (no manual review needed)
  - confidence <  threshold  -> keep in the queue, but refresh its AI suggestion
                                so /review shows the new category

DRY-RUN by default (writes nothing). Pass --apply to actually upload + dequeue.

IMPORTANT: with --apply, do not use /review or /upload in Discord while this
runs, to avoid concurrent writes to the same sheet.

Usage:
    python scripts/recategorize_pending.py <user_id>            # dry-run
    python scripts/recategorize_pending.py <user_id> --apply    # real run
"""

import sys
import os
import asyncio
import logging

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

from finance_core.pending_transactions import (  # noqa: E402
    get_user_pending_transactions, approve_transaction,
    load_pending_queue, _save_pending_queue,
)
from finance_core.categorization_engine import (  # noqa: E402
    create_categorization_engine,
)
from finance_core.google_sheets import GoogleSheetsExporter  # noqa: E402
from finance_core.background_upload import get_upload_queue  # noqa: E402
from config.config_settings import (  # noqa: E402
    GOOGLE_CREDENTIALS_PATH, GSHEET_NAME,
)

logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
THRESHOLD = 0.75


def _amt(tx):
    try:
        return float(tx.get('transaction_amount', {}).get('amount', 0))
    except (TypeError, ValueError):
        return 0.0


async def main():
    args = [a for a in sys.argv[1:]]
    apply = '--apply' in args
    ids = [a for a in args if not a.startswith('--')]
    if len(ids) != 1:
        print("Usage: recategorize_pending.py <user_id> [--apply]")
        sys.exit(1)
    user_id = int(ids[0])

    pending = get_user_pending_transactions(user_id)
    if not pending:
        print(f"No pending transactions for user {user_id}. Nothing to do.")
        return

    print(f"Re-categorizing {len(pending)} pending transactions "
          f"for user {user_id}  (mode: {'APPLY' if apply else 'DRY-RUN'})")
    print(f"Target sheet: {GSHEET_NAME}\n")

    txs = [item['transaction'] for item in pending]
    engine = create_categorization_engine(
        ai_enabled=True, ai_confidence_threshold=THRESHOLD)
    if not engine.ai_enabled:
        print("ERROR: AI categorization did not initialize. Aborting.")
        sys.exit(1)

    results = await engine.batch_categorize(txs)

    auto, manual = [], []
    for item, res in zip(pending, results):
        if res.category and res.confidence >= THRESHOLD:
            auto.append((item, res))
        else:
            manual.append((item, res))

    print(f"=== {len(auto)} will AUTO-CATEGORIZE (>= {THRESHOLD}) ===")
    for item, res in auto:
        tx = item['transaction']
        print(f"  [{item['transaction_type']:7}] {tx.get('booking_date')} "
              f"{_amt(tx):>9.2f}  -> {res.category} / {res.description} "
              f"({res.confidence:.0%}, {res.method})")
    print(f"\n=== {len(manual)} stay for MANUAL /review (< {THRESHOLD}) ===")
    for item, res in manual:
        tx = item['transaction']
        sug = f"{res.category} ({res.confidence:.0%})" if res.category else "no AI result"
        print(f"  [{item['transaction_type']:7}] {tx.get('booking_date')} "
              f"{_amt(tx):>9.2f}  -> suggestion: {sug}")

    if not apply:
        print("\nDRY-RUN: nothing written. Re-run with --apply to upload + dequeue.")
        return

    # ---- APPLY ----
    exporter = GoogleSheetsExporter(GOOGLE_CREDENTIALS_PATH)
    exporter._get_worksheet()
    sheet = exporter.sheet
    queue = get_upload_queue()
    queue.exporter = exporter
    queue._detect_current_positions(user_id)
    exp_row = queue.current_expense_row
    inc_row = queue.current_income_row

    exp_items = [(i, r) for i, r in auto if i['transaction_type'] == 'expense']
    inc_items = [(i, r) for i, r in auto if i['transaction_type'] == 'income']

    # Ensure capacity
    need = max(exp_row + len(exp_items) - 1, inc_row + len(inc_items) - 1)
    if need > sheet.row_count:
        sheet.resize(rows=need + 50)

    def build_rows(items):
        rows = []
        for item, res in items:
            ok, data = approve_transaction(
                item['approval_id'], res.category, res.description, user_id)
            if ok:
                rows.append(exporter.format_transaction_for_sheet(
                    data['transaction']))
        return rows

    exp_rows = build_rows(exp_items)
    inc_rows = build_rows(inc_items)

    if exp_rows:
        rng = f"B{exp_row}:E{exp_row + len(exp_rows) - 1}"
        sheet.update(exp_rows, rng)
        print(f"\nUploaded {len(exp_rows)} expenses to {rng}")
    if inc_rows:
        rng = f"G{inc_row}:J{inc_row + len(inc_rows) - 1}"
        sheet.update(inc_rows, rng)
        print(f"Uploaded {len(inc_rows)} income to {rng}")

    # Refresh AI suggestion on the ones still needing manual review
    q = load_pending_queue()
    refreshed = 0
    for item, res in manual:
        aid = item['approval_id']
        if aid in q['pending'] and res.category:
            q['pending'][aid]['ai_category'] = res.category
            q['pending'][aid]['ai_description'] = res.description
            q['pending'][aid]['ai_confidence'] = res.confidence
            refreshed += 1
    _save_pending_queue(q)

    # Sort the sheet chronologically
    exp_sorted, inc_sorted = exporter.sort_transactions_by_date()
    print(f"Sorted sheet: {exp_sorted} expenses, {inc_sorted} income")
    print(f"Refreshed AI suggestion on {refreshed} still-manual items")
    print(f"\nDone. {len(exp_rows) + len(inc_rows)} auto-uploaded, "
          f"{len(manual)} remain in /review.")


if __name__ == "__main__":
    asyncio.run(main())
