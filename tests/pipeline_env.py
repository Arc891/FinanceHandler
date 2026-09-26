"""
A pipeline wired to fakes, for tests/test_process_upload.py and tests/test_reconcile.py.

Everything Google is FakeWorkbooks; the categoriser is FakeEngine; the clock is
a FakeClock the engine can advance to trip the AI budget. ``Crash`` is a
BaseException, so it passes every ``except Exception`` in the pipeline the way
a killed process would, leaving the files on disk as they were at that point.
A fresh ``Env.pipeline()`` over the same directories is the restarted bot.
"""

from functools import partial

from csv_rows import asn_row, write_csv
from fakes import FakeWorkbooks, make_month

from finance_core import export
from finance_core.categorization_engine import CategorizationResult
from finance_core.google_retry import with_retry
from finance_core.ledger import Ledger
from finance_core.period_state import DEFAULTS, save_anchor
from finance_core.periods import Anchor, parse_date
from finance_core.row_tuple import EXPENSES, INCOME
from finance_core.sheet_index import load_index, save_index
from finance_core.sheet_registry import RegistryConfig, SheetRegistry

no_sleep_retry = partial(with_retry, sleep=lambda s: None)


class Crash(BaseException):
    """The process died here."""


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeEngine:
    """
    Stands in for CategorizationEngine.batch_categorize.

    Income is regex-matched; an expense whose remittance contains FLAG comes
    back below the threshold, one with MARK from a marked rule; SAME gives every such row the description
    "Same"; every other expense is ai_auto. Once the clock
    has passed the deadline, AI rows come back 'none', as the real engine's
    cancelled chunks do. ``before_call(label)`` runs at the start of each call.
    """

    def __init__(self, clock):
        self.clock = clock
        self.calls = []            # [(period_label, n_rows, deadline)]
        self.before_call = None
        self.spend = {}            # label -> seconds this call takes on the clock

    async def batch_categorize(self, transactions, deadline=None, **kwargs):
        label = transactions[0].get("period_label") if transactions else None
        self.calls.append((label, len(transactions), deadline))
        if self.before_call:
            self.before_call(label)
        self.clock.t += self.spend.get(label, 0.0)
        out_of_time = deadline is not None and self.clock() >= deadline
        results = []
        for tx in transactions:
            rem = (tx.get("remittance_information") or [""])[0]
            seq = tx.get("bank_sequence_no")
            if tx["credit_debit_indicator"] == "CRDT":
                results.append(CategorizationResult("DUO", f"Income {seq}", 1.0, "regex"))
            elif out_of_time:
                results.append(CategorizationResult(None, None, 0.0, "none"))
            elif "SAME" in rem:                    # distinct transactions, identical sheet rows
                results.append(CategorizationResult("Boodschappen", "Same", 0.9, "ai_auto"))
            elif "MARK" in rem:
                results.append(CategorizationResult("Huishouden", f"Shop {seq}", 1.0, "regex", marked=True))
            elif "FLAG" in rem:
                results.append(CategorizationResult("Uit eten", f"Guess {seq}", 0.4, "ai_manual_needed"))
            else:
                results.append(CategorizationResult("Boodschappen", f"Desc {seq}", 0.9, "ai_auto"))
        return results


# ── synthetic exports ─────────────────────────────────────────────────────────

_seq = [5000]


def row(date, amount="-10.00", counterparty="Winkel", remittance="aankoop", seq=None):
    if seq is None:
        _seq[0] += 1
        seq = str(_seq[0])
    return asn_row(date=date, counterparty=counterparty, amount=amount, seq=seq, remittance=remittance)


def duo(date, seq=None):
    return row(date, amount="314.10", counterparty="DUO Hoofdrekening", remittance="Studiefinanciering", seq=seq)


def three_boundary_rows():
    """Anchor 24-05-2026 (06/2026); DUO on 24-06, 24-07, 24-08: periods 06 (leading), 07, 08, 09."""
    rows = []
    for month, n in ((6, 4), (7, 5), (8, 3), (9, 2)):
        if month > 6:
            rows.append(duo(f"24-{month - 1:02d}-2026"))
        start = 25 if month > 6 else 10
        m = month - 1 if month > 6 else month
        for i in range(n):
            day = start + i
            rows.append(row(f"{day:02d}-{m:02d}-2026", amount=f"-{11 + i}.25"))
    return rows


# ── the environment ───────────────────────────────────────────────────────────

class Env:
    def __init__(self, tmp_path, *, months=("06/2026",), anchor=("24-05-2026", "06/2026"), **config):
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.tmp = tmp_path
        self.wb = FakeWorkbooks()
        self.index_path = tmp_path / "sheet_index.json"
        self.ledger_path = tmp_path / "upload_ledger.json"
        self.state_path = tmp_path / "period_state.json"
        self.runs_dir = tmp_path / "runs"
        self.uploads_dir = tmp_path / "uploads"
        self.failed_path = tmp_path / "failed_uploads.json"
        self.clock = FakeClock()
        self.engine = FakeEngine(self.clock)
        self.config_overrides = config
        index = {}
        for label in months:
            sid = "id-" + label.replace("/", "-")
            self.wb.add_book(make_month(sid, label))
            index[label] = {"id": sid, "created_by_bot": False, "created_at": None}
        save_index(self.index_path, index)
        if anchor:
            save_anchor(self.state_path, Anchor(parse_date(anchor[0]), anchor[1]))
        self._uploads = 0
        export.release_guard()

    def config(self):
        cfg = dict(
            runs_dir=str(self.runs_dir), uploads_dir=str(self.uploads_dir),
            period_state_path=str(self.state_path), failed_path=str(self.failed_path),
            ai_run_max_minutes=30.0, budget_trip_action="write_flagged", summary_flagged_lines=40,
            split=dict(markers=list(DEFAULTS["PERIOD_BOUNDARY_MARKERS"]),
                       min_amount=DEFAULTS["PERIOD_BOUNDARY_MIN_AMOUNT"],
                       min_days=DEFAULTS["PERIOD_MIN_DAYS"], max_days=DEFAULTS["PERIOD_MAX_DAYS"],
                       step_days=DEFAULTS["PERIOD_STEP_DAYS"], split_day=DEFAULTS["PERIOD_LABEL_SPLIT_DAY"]),
        )
        cfg.update(self.config_overrides)
        return export.PipelineConfig(**cfg)

    def registry(self):
        cfg = RegistryConfig(index_path=str(self.index_path), template_id=FakeWorkbooks.TEMPLATE_ID,
                             folder_id=FakeWorkbooks.FOLDER_ID)
        return SheetRegistry(self.wb, cfg, retry=no_sleep_retry)

    def ledger(self):
        return Ledger(self.ledger_path)

    def pipeline(self, ledger=None):
        """A freshly started bot over the same state files."""
        export.release_guard()
        return export.Pipeline(self.config(), registry=self.registry(), ledger=ledger or self.ledger(),
                               engine=self.engine, clock=self.clock)

    def save_upload(self, *files):
        """Write each list of rows as a CSV under uploads/<upload_id>/; returns (upload_id, paths)."""
        self._uploads += 1
        upload_id = f"20260925-12000{self._uploads}-test"
        folder = self.uploads_dir / upload_id
        folder.mkdir(parents=True)
        paths = [write_csv(folder / f"export{i + 1}.csv", rows) for i, rows in enumerate(files)]
        return upload_id, paths

    async def upload(self, *files, force=False, pipeline=None, progress=None):
        upload_id, paths = self.save_upload(*files)
        report = await (pipeline or self.pipeline()).process_upload(upload_id, paths, force=force,
                                                                    progress=progress)
        return upload_id, report

    # ── inspection ──────────────────────────────────────────────────────────
    def sheet(self, label):
        return self.wb.books[load_index(self.index_path)[label]["id"]]

    def block_rows(self, label, block):
        ws = self.sheet(label).transactions
        return ws.rows(block.first_col, block.last_col)

    def written(self, label):
        return len(self.block_rows(label, EXPENSES)) + len(self.block_rows(label, INCOME))

    def total_written(self):
        return sum(self.written(label) for label in load_index(self.index_path))

    def run(self, upload_id):
        return export.RunStore(self.runs_dir).load(upload_id)

    def period(self, upload_id, label):
        return next(p for p in self.run(upload_id)["periods"] if p["label"] == label)
