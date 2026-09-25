"""
Upload ledger and write audit (plan 4.6).

Two records with different licences, deliberately kept apart:

- the **dedup** record (``record_written``), written *before* a block is
  appended. It may over-record, never under-record: a spurious entry costs a
  skipped row, a missing one silently writes the row twice on the next
  overlapping upload.
- the **write audit** (``record_audit``), written *after* the append from
  exactly what landed. Undo is destructive and content-addressed, so the audit
  must never name a row that is not in the sheet.
"""

import hashlib
import json
import os
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from finance_core.config_access import project_path, setting
from finance_core.row_tuple import block_for, canonical_date
from finance_core.sheet_index import label_sort_key


def _amount(tx) -> Decimal:
    raw = (tx.get("transaction_amount") or {}).get("amount", "0")
    try:
        return Decimal(str(raw).replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0.00")


def counterparty(tx) -> str:
    return ((tx.get("debtor") or {}).get("name") or (tx.get("creditor") or {}).get("name") or "").strip()


def remittance_raw(tx) -> str:
    """The remittance as the bank wrote it, before csv_helper's normalisation."""
    if "remittance_raw" in tx:
        return (tx["remittance_raw"] or "").strip()
    rem = tx.get("remittance_information") or [""]
    return (rem[0] or "").strip()


def strong_key(tx) -> str:
    """sha1(booking_date | amount | counterparty | raw remittance | bank_sequence_no)."""
    parts = [
        (tx.get("booking_date") or "").strip(),
        f"{_amount(tx)}",
        counterparty(tx),
        remittance_raw(tx),
        (tx.get("bank_sequence_no") or "").strip(),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def weak_key(tx) -> str:
    """ISO date | abs(amount) | block: the only thing a row the old pipeline wrote still shares."""
    return weak_key_parts(canonical_date(tx.get("booking_date", "")), abs(_amount(tx)), block_for(tx).name)


def weak_key_parts(iso_date: str, abs_amount, block_name: str) -> str:
    return f"{iso_date}|{Decimal(str(abs_amount)).quantize(Decimal('0.01'))}|{block_name}"


# ── the ledger file ──────────────────────────────────────────────────────────
#
# data/upload_ledger.json:
#   strong: {key: {"weak": weak_key, "labels": {label: {upload_id: count}}}}
#       Per (upload_id, key, label) the count is the number of occurrences that
#       run recorded, set with max(), so re-recording is a no-op; the key's total
#       is the sum over labels and runs (multiset semantics).
#   seeded: {label: {weak_key: count}}   rows the old pipeline wrote (seed_state.py)
#   runs:   {upload_id: {anchor_before, started_at, undone_at,
#                        sheets: {sheet_id: {block: [[key, [date, amount, desc, cat]], ...]}}}}

@dataclass(frozen=True)
class Skip:
    tx: dict
    reason: str          # "strong": already uploaded; "weak": probably written by the old pipeline
    label: str           # the month it was found in


class Ledger:
    def __init__(self, path):
        self.path = os.fspath(path)
        self._lock = threading.RLock()

    @classmethod
    def from_settings(cls) -> "Ledger":
        return cls(project_path(setting("UPLOAD_LEDGER_PATH", "data/upload_ledger.json")))

    # ── storage ───────────────────────────────────────────────────────────
    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"version": 1, "strong": {}, "seeded": {}, "runs": {}}
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("strong", "seeded", "runs"):
            data.setdefault(key, {})
        return data

    def _save(self, data: dict) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ledger.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ── dedup ─────────────────────────────────────────────────────────────
    def filter_new(self, txs) -> Tuple[list, List[Skip]]:
        """
        Split ``txs`` into rows not yet in any sheet and skipped rows.

        Strong hits are consumed with multiplicity in any label; otherwise a
        weak hit with remaining count in a *seeded* label skips the row.
        """
        data = self._load()
        strong_avail = {}
        for key, entry in data["strong"].items():
            strong_avail[key] = [[label, sum(runs.values())] for label, runs in entry["labels"].items()]
        seeded = {label: Counter(counts) for label, counts in data["seeded"].items()}
        new, skipped = [], []
        for tx in txs:
            slots = strong_avail.get(strong_key(tx), [])
            slot = next((s for s in slots if s[1] > 0), None)
            if slot:
                slot[1] -= 1
                skipped.append(Skip(tx, "strong", slot[0]))
                continue
            wkey = weak_key(tx)
            label = next((lb for lb in sorted(seeded, key=label_sort_key) if seeded[lb][wkey] > 0), None)
            if label:
                seeded[label][wkey] -= 1
                skipped.append(Skip(tx, "weak", label))
                continue
            new.append(tx)
        return new, skipped

    def record_written(self, upload_id: str, label: str, txs) -> None:
        """The dedup record, written BEFORE the append. Idempotent; may over-record, never under-record."""
        counts = Counter(strong_key(tx) for tx in txs)
        weak = {strong_key(tx): weak_key(tx) for tx in txs}
        with self._lock:
            data = self._load()
            for key, n in counts.items():
                entry = data["strong"].setdefault(key, {"weak": weak[key], "labels": {}})
                runs = entry["labels"].setdefault(label, {})
                runs[upload_id] = max(runs.get(upload_id, 0), n)
            self._save(data)

    def seed_label(self, label: str, weak_keys) -> None:
        """Replace the seeded weak counts of ``label`` (scripts/seed_state.py)."""
        with self._lock:
            data = self._load()
            data["seeded"][label] = dict(Counter(weak_keys))
            self._save(data)

    # ── runs and the write audit ──────────────────────────────────────────
    def start_run(self, upload_id: str, anchor_before) -> None:
        """
        Open the audit for a run. ``anchor_before`` is the full content of the
        period state file before the run (None when there was none);
        undo_upload.py writes it back verbatim. Idempotent: the first call wins.
        """
        with self._lock:
            data = self._load()
            data["runs"].setdefault(upload_id, {
                "anchor_before": anchor_before,
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "undone_at": None,
                "sheets": {},
            })
            self._save(data)

    def record_audit(self, upload_id: str, sheet_id: str, block_name: str, pairs) -> None:
        """
        The undo record, written AFTER the append from exactly what landed.

        Merged as a multiset maximum, so reconciliation re-auditing rows the
        first attempt already audited never doubles them.
        """
        with self._lock:
            data = self._load()
            run = data["runs"].setdefault(upload_id, {"anchor_before": None, "started_at": None,
                                                      "undone_at": None, "sheets": {}})
            stored = run["sheets"].setdefault(sheet_id, {}).setdefault(block_name, [])
            have = Counter((k, tuple(t)) for k, t in stored)
            want = Counter((k, tuple(t)) for k, t in pairs)
            for item, n in want.items():
                for _ in range(n - have[item]):
                    stored.append([item[0], list(item[1])])
            self._save(data)

    def run(self, upload_id: str) -> Optional[dict]:
        return self._load()["runs"].get(upload_id)

    def audited_rows(self, upload_id: str) -> dict:
        """{sheet_id: {block: [RowTuple, ...]}} for the run, empty blocks left out."""
        run = self.run(upload_id) or {}
        return {sid: {b: [tuple(t) for _, t in rows] for b, rows in blocks.items() if rows}
                for sid, blocks in run.get("sheets", {}).items()
                if any(blocks.values())}

    def forget_run(self, upload_id: str) -> None:
        """After an undo: drop the run's dedup records and audit, so its rows count as new again."""
        with self._lock:
            data = self._load()
            for key in list(data["strong"]):
                labels = data["strong"][key]["labels"]
                for label in list(labels):
                    labels[label].pop(upload_id, None)
                    if not labels[label]:
                        del labels[label]
                if not labels:
                    del data["strong"][key]
            run = data["runs"].get(upload_id)
            if run is not None:
                run["sheets"] = {}
                run["undone_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._save(data)


def collapse_within_upload(files) -> Tuple[list, int]:
    """
    Merge the transactions of several attachments of one /upload.

    Per strong key, keep the MAXIMUM count seen in any one file, never the sum:
    a row present in two overlapping exports collapses to one, while two genuine
    same-day identical rows (present twice in each file) stay two. Returns
    (transactions in first-seen order, number of rows collapsed away).
    """
    keep = Counter()
    for txs in files:
        for key, n in Counter(strong_key(tx) for tx in txs).items():
            keep[key] = max(keep[key], n)
    out, total = [], 0
    for txs in files:
        for tx in txs:
            total += 1
            key = strong_key(tx)
            if keep[key] > 0:
                keep[key] -= 1
                out.append(tx)
    return out, total - len(out)
