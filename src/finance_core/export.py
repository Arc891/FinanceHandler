"""
The upload pipeline: /upload, /resume, /cancel, /sort and /status (plan 4.1, 4.6, 4.7).

One upload of one or more ASN exports goes through:

    load + drop unparsable dates -> collapse_within_upload -> ledger.filter_new
    -> split into periods (SuspiciousSplitError writes nothing) -> save the anchor
    -> per period, in date order: resolve -> categorise -> append (4.6 COMMIT)
    -> sort every touched sheet without an `appending` period -> summary

Every accepted row is written; an uncertain one is written flagged (4.9). The
run state (run_state.RunStore) holds the rows of every period that is not yet
`written`, and is saved after every status transition, so any exit leaves a
run that /resume can finish. A period that entered `appending` only ever
leaves it for `written`: /resume reconciles it against its recorded baseline
(4.6 RECONCILE), never re-appends it blind.

Nothing here knows Discord. ``progress`` is an async callable taking one line;
refusals raise ``RunRefused`` with the message to show. Google calls are
synchronous and may sleep in a retry, so they run in a worker thread.

Log lines carry labels, statuses and counts only, never a name, description
or amount (tests/test_log_privacy.py).
"""

import asyncio
import logging
import os
import shutil
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, List, Optional

from google.auth.exceptions import RefreshError

from finance_core import run_state as rs
from finance_core.config_access import project_path, setting
from finance_core.csv_helper import load_transactions_from_csv
from finance_core.flagging import apply_category
from finance_core.google_auth import GoogleAuthError
from finance_core.google_sheets import format_transaction_for_sheet
from finance_core.ledger import collapse_within_upload, strong_key
from finance_core.period_state import load_anchor, read_state, split_settings, write_state
from finance_core.periods import (SuspiciousSplitError, advance_anchor, anchor_to_state, format_date,
                                  parse_date, split_into_periods)
from finance_core.row_tuple import BLOCKS, EXPENSES, block_for, canonical
from finance_core.run_state import RunStore
from finance_core.sheet_writer import (BlockBaseline, commit_append, data_start_row, digest, intended_cells,
                                       plan_append, read_block, sort_by_date)

logger = logging.getLogger(__name__)

AUTH_ERRORS = (GoogleAuthError, RefreshError)
LOGIN_REMEDY = "run scripts/google_login.py on the workstation, copy the token to the Pi, then /resume"

Progress = Optional[Callable[[str], Awaitable[None]]]


class RunRefused(Exception):
    """The command is refused; the message says why and what to do instead."""


# ── the in-flight guard (single-process bot) ─────────────────────────────────

_current: Optional[dict] = None


def release_guard() -> None:
    global _current
    _current = None


def _take_guard(upload_id: str) -> None:
    global _current
    if _current is not None:
        raise RunRefused(f"a run started at {_current['at']} is in progress ({_current['upload_id']}); "
                         "wait for its summary")
    _current = {"upload_id": upload_id, "at": datetime.now().strftime("%H:%M")}


def new_upload_id(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{os.urandom(2).hex()}"


# ── configuration and the report ─────────────────────────────────────────────

@dataclass(frozen=True)
class PipelineConfig:
    runs_dir: str
    uploads_dir: str
    period_state_path: str
    split: dict
    failed_path: Optional[str] = None
    ai_run_max_minutes: float = 30.0
    budget_trip_action: str = "write_flagged"      # or "stop" (plan 4.7)
    summary_flagged_lines: int = 40

    def __post_init__(self):
        if self.budget_trip_action not in ("write_flagged", "stop"):
            raise ValueError(f"AI_BUDGET_TRIP_ACTION must be 'write_flagged' or 'stop', "
                             f"not {self.budget_trip_action!r}")

    @classmethod
    def from_settings(cls) -> "PipelineConfig":
        return cls(
            runs_dir=rs.runs_dir(),
            uploads_dir=project_path(setting("UPLOAD_DIR", "data/uploads")),
            period_state_path=project_path(setting("PERIOD_STATE_PATH", "data/period_state.json")),
            split=split_settings(),
            failed_path=project_path(setting("FAILED_UPLOADS_PATH", "data/failed_uploads.json")),
            ai_run_max_minutes=float(setting("AI_RUN_MAX_MINUTES", 30)),
            budget_trip_action=setting("AI_BUDGET_TRIP_ACTION", "write_flagged"),
            summary_flagged_lines=int(setting("SUMMARY_FLAGGED_LINES", 40)),
        )


@dataclass
class RunReport:
    upload_id: str
    text: str
    complete: bool
    flagged_attachment: Optional[str] = None      # the full flagged list when the summary is capped
    periods: List[dict] = field(default_factory=list)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _status_text(p: dict) -> str:
    if p["status"] == rs.FAILED:
        return f"failed ({p.get('failed_reason')})"
    return p["status"]


def _period_line(p: dict) -> str:
    c = p["counts"]
    parts = [f"{p['label']}: {_status_text(p)}",
             f"{_plural(c['rows'], 'row')} ({c['expenses']} expenses, {c['income']} income)"]
    if p.get("created"):
        parts.append("sheet created")
    if p.get("categorised"):
        parts.append(f"{c['flagged']} flagged")
    return ", ".join(parts)


def _todo(run: dict, p: dict) -> str:
    uid = run["upload_id"]
    head = f"{p['label']}: {p['status']}, {_plural(p['counts']['rows'], 'row')}"
    if p["status"] == rs.APPENDING:
        return (f"{head}: the write did not finish ({p.get('last_error') or 'interrupted'}); "
                f"/resume {uid} reconciles it; its sheet is left unsorted until then")
    if p["status"] == rs.FAILED:
        return f"{head}: {p.get('failed_reason')}; fix the cause, then /resume {uid}"
    if p.get("not_started"):
        return f"{head}: not started ({p['not_started']}); /resume {uid} continues"
    return f"{head}: not written yet; /resume {uid}"


def _flagged_line(f: dict) -> str:
    guess = (f"{f['ai_category']} ({f['ai_confidence']:.2f})" if f.get("ai_category")
             else "no AI answer")
    return f"{f.get('date', '?')}  {f.get('amount', '?')}  {f.get('description', '')}  -> {guess}"


def render(run: dict, *, flagged_cap: int) -> RunReport:
    notes = run.get("notes") or {}
    periods = run.get("periods") or []
    lines = [f"Upload {run['upload_id']}"]
    if "loaded" in notes:
        lines.append(f"{_plural(notes['loaded'], 'row')} read from {_plural(len(run['files']), 'file')}; "
                     f"{notes.get('accepted', 0)} new.")
    for d in notes.get("dropped", []):
        lines.append(f"Dropped: {d}")
    skipped = notes.get("skipped") or {}
    if skipped.get("strong"):
        lines.append(f"Skipped: {skipped['strong']} already uploaded.")
    for label, n in sorted((skipped.get("weak") or {}).items()):
        lines.append(f"Skipped: {n} probably already in {label} (written before the ledger).")
    if notes.get("collapsed"):
        lines.append(f"{notes['collapsed']} duplicated across attachments, collapsed to one.")
    if notes.get("refused"):
        lines.append(f"Refused: {notes['refused']}")
        lines.append("Nothing was written and the period anchor is unchanged.")
    if notes.get("boundaries"):
        lines.append("Boundaries: " + ", ".join(f"{d} -> {lbl}" for d, lbl in notes["boundaries"]))
    for w in notes.get("warnings", []):
        lines.append(f"Warning: {w}")
    if notes.get("skipped_labels"):
        lines.append("Skipped months (no boundary in the upload): " + ", ".join(notes["skipped_labels"]))

    if periods:
        lines.append("Periods:")
        lines += [f"  {_period_line(p)}" for p in periods]
    for p in periods:
        lines += [f"Note: {n}" for n in p.get("notes", [])]
        if p.get("partial_undo"):
            lines.append(f"Note: {p['label']}: the content fallback was used, so undo coverage for this "
                         f"period is partial, and a row equal to one already in the sheet may have been "
                         f"skipped. Compare the period's row count ({p['counts']['rows']}) against the sheet.")
    last = run.get("last_pass") or {}
    if last.get("tripped"):
        minutes = last.get("budget_minutes")
        if last.get("trip_action") == "stop":
            lines.append(f"AI budget of {minutes:g} minutes ran out during {last['tripped']}: its remaining "
                         "rows were written flagged, and later periods were not started.")
        else:
            lines.append(f"AI budget of {minutes:g} minutes ran out during {last['tripped']}: the remaining "
                         "rows were written flagged with the bank's text as description.")
    for label in last.get("unsorted", []):
        lines.append(f"{label}: left unsorted pending /resume.")
    for e in last.get("sort_errors", []):
        lines.append(f"Sort: {e}")
    if run.get("stopped"):
        lines.append(f"Stopped: {run['stopped']}")

    open_periods = [p for p in periods if p["status"] != rs.WRITTEN]
    if open_periods:
        lines.append("Not written:")
        lines += [f"  {_todo(run, p)}" for p in open_periods]
    elif not run.get("split_done") and not run.get("closed"):
        lines.append(f"Not split yet: /resume {run['upload_id']} starts it again.")

    flagged = [f for p in periods for f in p.get("flagged", [])]
    attachment = None
    if flagged:
        lines.append("Flagged rows (the AI guess that was not used):")
        lines += [f"  {_flagged_line(f)}" for f in flagged[:flagged_cap]]
        if len(flagged) > flagged_cap:
            lines.append(f"  ... and {len(flagged) - flagged_cap} more (full list attached)")
            attachment = "\n".join(_flagged_line(f) for f in flagged) + "\n"
    complete = run.get("closed") == "complete"
    return RunReport(run["upload_id"], "\n".join(lines), complete, attachment,
                     [{"label": p["label"], "status": p["status"], "rows": p["counts"]["rows"],
                       "flagged": p["counts"]["flagged"], "created": p.get("created", False)}
                      for p in periods])


# ── the pipeline ─────────────────────────────────────────────────────────────

def _status_of(run: dict, label: str) -> Optional[str]:
    return next((p["status"] for p in run["periods"] if p["label"] == label), None)


def _txs(p: dict) -> list:
    return p["rows"]["expenses"] + p["rows"]["income"]


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


class Pipeline:
    def __init__(self, config: PipelineConfig, *, registry, ledger, engine, clock=time.monotonic):
        self.config = config
        self.registry = registry
        self.ledger = ledger
        self.engine = engine
        self.clock = clock
        self.store = RunStore(config.runs_dir)
        self._sheets = {}          # label -> spreadsheet opened in this pass

    @classmethod
    def from_settings(cls) -> "Pipeline":
        from finance_core.categorization_engine import create_categorization_engine
        from finance_core.ledger import Ledger
        from finance_core.sheet_registry import GoogleWorkbooks, RegistryConfig, SheetRegistry
        registry = SheetRegistry(GoogleWorkbooks.from_credentials(), RegistryConfig.from_settings())
        return cls(PipelineConfig.from_settings(), registry=registry, ledger=Ledger.from_settings(),
                   engine=create_categorization_engine(ai_enabled=True))

    # ── commands ──────────────────────────────────────────────────────────
    async def process_upload(self, upload_id: str, files, *, force: bool = False,
                             progress: Progress = None) -> RunReport:
        """/upload: ``files`` are the saved attachments, in attachment order."""
        self._refuse_if_appending()
        _take_guard(upload_id)
        try:
            folders = {os.path.dirname(os.path.abspath(f)) for f in files}
            run = self.store.create(upload_id, files=[os.fspath(f) for f in files], force=force,
                                    upload_dir=folders.pop() if len(folders) == 1 else None,
                                    anchor_before=read_state(self.config.period_state_path))
            logger.info("Run %s started with %d file(s)", upload_id, len(files))
            return await self._drive(run, progress)
        finally:
            release_guard()

    async def resume(self, upload_id: Optional[str] = None, *, progress: Progress = None) -> RunReport:
        """/resume: the named open run, or the newest one. Never re-splits a split run."""
        run = self._pick_open(upload_id, "resume")
        others = [(u, lbl) for u, lbl, _ in self.store.appending_periods() if u != run["upload_id"]]
        if others:
            u, lbl = others[0]
            raise RunRefused(f"run {u} has {lbl} still appending; /resume {u} first")
        _take_guard(run["upload_id"])
        try:
            logger.info("Run %s resumed", run["upload_id"])
            return await self._drive(run, progress)
        finally:
            release_guard()

    def cancel(self, upload_id: Optional[str] = None, *, confirm: bool = False) -> str:
        """/cancel: abandon an open run. Never undoes a write; undo_upload.py does that."""
        run = self._pick_open(upload_id, "cancel")
        uid = run["upload_id"]
        if _current is not None and _current["upload_id"] == uid:
            raise RunRefused(f"run {uid} is in progress; wait for its summary")
        appending = [p["label"] for p in run["periods"] if p["status"] == rs.APPENDING]
        if appending:
            raise RunRefused(
                f"run {uid} has {', '.join(appending)} still appending. First /resume {uid} to "
                f"reconcile it; then, if the run should be reversed, scripts/undo_upload.py {uid}. "
                "Undo before resume would compact a half-written block and lose its baseline.")
        pending = [p for p in run["periods"] if p["status"] != rs.WRITTEN]
        discard = sum(p["counts"]["rows"] for p in pending)
        if discard and not confirm:
            raise RunRefused(f"cancelling run {uid} discards {_plural(discard, 'row')} not yet written "
                             f"({', '.join(p['label'] for p in pending)}); repeat with confirm: true")
        self.store.close(run, "abandoned")
        self._remove_uploads(run)
        logger.info("Run %s abandoned, %d row(s) discarded", uid, discard)
        return f"Run {uid} cancelled; {_plural(discard, 'row')} not written were discarded."

    async def sort(self, labels: Optional[List[str]] = None) -> List[str]:
        """/sort: the given months, or every sheet the last run touched."""
        self._refuse_if_appending(what="sorting")
        if labels is None:
            touched = [r for r in self.store.all_runs() if r.get("touched")]
            labels = touched[-1]["touched"] if touched else []
        return await asyncio.to_thread(self._sort_labels, list(labels))

    def status(self) -> str:
        """/status: every open run, naming each period that is not written."""
        runs = self.store.open_runs()
        if not runs:
            return "No open runs."
        return "\n\n".join(render(r, flagged_cap=self.config.summary_flagged_lines).text for r in runs)

    # ── refusals ──────────────────────────────────────────────────────────
    def _refuse_if_appending(self, what: str = "a new upload") -> None:
        appending = self.store.appending_periods()
        if appending:
            u, lbl, _ = appending[0]
            raise RunRefused(f"run {u} has {lbl} still appending, so {what} is refused: "
                             f"/resume {u} first to reconcile it")

    def _pick_open(self, upload_id: Optional[str], verb: str) -> dict:
        runs = self.store.open_runs()
        if upload_id is None:
            if not runs:
                raise RunRefused(f"no open run to {verb}")
            return runs[-1]
        run = next((r for r in runs if r["upload_id"] == upload_id), None)
        if run is None:
            raise RunRefused(f"no open run {upload_id} to {verb}")
        return run

    # ── the run ───────────────────────────────────────────────────────────
    async def _drive(self, run: dict, progress: Progress) -> RunReport:
        self._sheets = {}
        run["stopped"] = None
        run["last_pass"] = {"tripped": None, "unsorted": [], "sort_errors": [], "touched": [],
                            "budget_minutes": self.config.ai_run_max_minutes,
                            "trip_action": self.config.budget_trip_action}
        deadline = self.clock() + self.config.ai_run_max_minutes * 60
        if not run["split_done"]:
            await asyncio.to_thread(self._split, run)
        elif not run["anchor_saved"]:
            await asyncio.to_thread(self._save_anchor, run)
        if run["closed"] is None:
            await self._periods(run, deadline, progress)
            await asyncio.to_thread(self._closing_sort, run)
            if run["split_done"] and all(p["status"] == rs.WRITTEN for p in run["periods"]):
                self.store.close(run, "complete")
                self._remove_uploads(run)
            else:
                self.store.save(run)
        report = render(run, flagged_cap=self.config.summary_flagged_lines)
        logger.info("Run %s: %s", run["upload_id"],
                    dict(Counter(p["status"] for p in run["periods"])) or "no periods")
        return report

    def _split(self, run: dict) -> None:
        notes = run["notes"] = {}
        per_file, dropped = [], []
        for path in run["files"]:
            name = os.path.basename(path)
            try:
                txs = load_transactions_from_csv(path)
            except Exception as exc:
                notes["refused"] = f"could not read {name} ({type(exc).__name__})"
                self.store.close(run, "refused")
                self._remove_uploads(run)
                return
            good = []
            for tx in txs:
                try:
                    parse_date(tx["booking_date"])
                    good.append(tx)
                except ValueError:
                    dropped.append(f"{name} row {tx.get('csv_row', '?')}: unparsable date "
                                   f"{tx['booking_date']!r}")
            per_file.append(good)
        notes["loaded"] = sum(len(f) for f in per_file)
        notes["dropped"] = dropped
        txs, notes["collapsed"] = collapse_within_upload(per_file)
        txs.sort(key=lambda t: parse_date(t["booking_date"]))
        new, skips = self.ledger.filter_new(txs)
        weak = Counter(s.label for s in skips if s.reason == "weak")
        notes["skipped"] = {"strong": sum(1 for s in skips if s.reason == "strong"), "weak": dict(weak)}
        notes["accepted"] = len(new)

        anchor = load_anchor(self.config.period_state_path)
        try:
            result = split_into_periods(new, anchor=anchor, force=run["force"], **self.config.split)
        except SuspiciousSplitError as exc:
            notes["refused"] = str(exc)
            self.store.close(run, "refused")
            self._remove_uploads(run)
            logger.info("Run %s refused: suspicious split", run["upload_id"])
            return
        notes["boundaries"] = [[format_date(b), label] for b, label in result.boundaries]
        notes["warnings"] = list(result.warnings)
        notes["skipped_labels"] = list(result.skipped_labels)
        run["periods"] = [rs.new_period(p.label,
                                        [t for t in p.transactions if block_for(t) is EXPENSES],
                                        [t for t in p.transactions if block_for(t) is not EXPENSES])
                          for p in result.periods]
        run["anchor_after"] = anchor_to_state(advance_anchor(anchor, result))
        # Before anything is written: undo restores anchor_before from the ledger's run.
        self.ledger.start_run(run["upload_id"], run["anchor_before"])
        run["split_done"] = True
        self.store.save(run)
        self._save_anchor(run)

    def _save_anchor(self, run: dict) -> None:
        path = self.config.period_state_path
        current = read_state(path)
        if current == run["anchor_before"]:
            write_state(path, run["anchor_after"])
        elif current != run["anchor_after"]:
            run["notes"].setdefault("warnings", []).append(
                "the period anchor changed while this run was open; it was left as it is")
        run["anchor_saved"] = True
        self.store.save(run)

    async def _periods(self, run: dict, deadline: float, progress: Progress) -> None:
        last = run["last_pass"]
        for p in run["periods"]:
            if p["status"] == rs.WRITTEN:
                continue
            try:
                if p["status"] == rs.APPENDING:
                    await asyncio.to_thread(self._reconcile, run, p)
                else:
                    if (last["tripped"] and self.config.budget_trip_action == "stop"
                            and not p["categorised"]):
                        p["not_started"] = "AI budget spent"
                        self.store.save(run)
                        continue
                    p["not_started"] = None
                    if not await asyncio.to_thread(self._resolve, run, p):
                        continue
                    if not p["categorised"]:
                        if not await self._categorise(run, p, deadline):
                            continue
                        if self.clock() >= deadline and not last["tripped"]:
                            last["tripped"] = p["label"]
                    await asyncio.to_thread(self._append, run, p)
            except AUTH_ERRORS as exc:
                run["stopped"] = f"Google authorisation failed ({type(exc).__name__}); {LOGIN_REMEDY}"
                self.store.save(run)
                logger.error("Run %s stopped at %s: %s", run["upload_id"], p["label"], type(exc).__name__)
                return
            if p["status"] in (rs.WRITTEN, rs.APPENDING):
                last["touched"].append(p["label"])
            if p["status"] == rs.WRITTEN:
                await self._progress(progress, f"{p['label']}: {_plural(p['counts']['rows'], 'row')} "
                                               f"written, {p['counts']['flagged']} flagged")
            else:
                await self._progress(progress, f"{p['label']}: {_status_text(p)}")

    async def _progress(self, progress: Progress, line: str) -> None:
        if progress is None:
            return
        try:
            await progress(line)
        except Exception:
            logger.exception("Could not post a progress line")

    # ── one period ────────────────────────────────────────────────────────
    def _fail(self, run: dict, p: dict, reason: str) -> bool:
        p["status"] = rs.FAILED
        p["failed_reason"] = reason
        self.store.save(run)
        logger.warning("Run %s: %s failed", run["upload_id"], p["label"])
        return False

    def _resolve(self, run: dict, p: dict) -> bool:
        try:
            resolved = self.registry.resolve(p["label"], upload_id=run["upload_id"],
                                             period_status=lambda label: _status_of(run, label))
        except AUTH_ERRORS:
            raise
        except Exception as exc:
            return self._fail(run, p, _error(exc))
        sh = resolved.spreadsheet
        self._sheets[p["label"]] = sh
        p["sheet_id"] = sh.id
        p["created"] = p["created"] or resolved.created
        p["notes"] = list(dict.fromkeys(p["notes"] + resolved.notes()))
        p["status"] = rs.CATEGORISED if p["categorised"] else rs.RESOLVED
        p["failed_reason"] = None
        self.store.save(run)
        return True

    async def _categorise(self, run: dict, p: dict, deadline: float) -> bool:
        txs = sorted(_txs(p), key=lambda t: parse_date(t["booking_date"]))
        try:
            results = await self.engine.batch_categorize(txs, deadline=deadline)
            if len(results) != len(txs):
                raise RuntimeError(f"{len(results)} results for {len(txs)} rows")
        except Exception as exc:
            return self._fail(run, p, f"categorisation failed: {_error(exc)}")
        rows = {"expenses": [], "income": []}
        flagged = []
        for tx, result in zip(txs, results):
            row, guess = apply_category(tx, result)
            rows[block_for(row).name].append(row)
            if guess:
                cells = format_transaction_for_sheet(row)
                flagged.append({"key": strong_key(tx), "date": tx["booking_date"],
                                "amount": f"{cells[1]:.2f}", "description": cells[2], **guess})
        p["rows"] = rows
        p["flagged"] = flagged
        p["counts"]["flagged"] = len(flagged)
        p["categorised"] = True
        p["status"] = rs.CATEGORISED
        self.store.save(run)
        return True

    def _context(self, run, p) -> dict:
        return {"upload_id": run["upload_id"], "period_label": p["label"]}

    def _append(self, run: dict, p: dict) -> None:
        """4.6 COMMIT, first attempt."""
        sh = self._sheets[p["label"]]
        blocks = [(b, p["rows"][b.name]) for b in BLOCKS if p["rows"][b.name]]
        try:
            baselines = {b.name: plan_append(sh, b).to_dict() for b, _ in blocks}     # 1
        except AUTH_ERRORS:
            raise
        except Exception as exc:
            self._fail(run, p, f"could not read the sheet: {_error(exc)}")
            return
        p["baseline"] = baselines                                                      # 2
        p["status"] = rs.APPENDING                                                     # 3
        p["last_error"] = None
        p["reconcile"] = {}
        self.store.save(run)
        try:
            self.ledger.record_written(run["upload_id"], p["label"], _txs(p))          # 4
            for block, txs in blocks:
                pairs = commit_append(sh, block, txs, context=self._context(run, p),   # 5
                                      failed_path=self.config.failed_path)
                self.ledger.record_audit(run["upload_id"], sh.id, block.name, pairs)   # 6
        except Exception as exc:
            p["last_error"] = _error(exc)
            self.store.save(run)
            logger.warning("Run %s: write to %s failed; the period stays appending",
                           run["upload_id"], p["label"])
            if isinstance(exc, AUTH_ERRORS):
                raise
            return
        self._mark_written(run, p)                                                     # 7

    def _mark_written(self, run: dict, p: dict) -> None:
        p["status"] = rs.WRITTEN
        p["rows"] = {"expenses": [], "income": []}
        p["baseline"] = {}
        p["last_error"] = None
        touched = run.setdefault("touched", [])
        if p["label"] not in touched:
            touched.append(p["label"])
        self.store.save(run)

    def _reconcile(self, run: dict, p: dict) -> None:
        """4.6 RECONCILE, per block, for a period left `appending`."""
        try:
            sh = self.registry.lookup(p["label"])
            if sh is None or sh.id != p["sheet_id"]:
                raise RuntimeError(f"the index no longer maps {p['label']} to the sheet this run wrote to")
            self._sheets[p["label"]] = sh
            for block in BLOCKS:
                txs = p["rows"][block.name]
                if not txs:
                    continue
                recorded = p["baseline"].get(block.name)
                if recorded is None:
                    raise RuntimeError(f"no baseline recorded for the {block.name} block")
                path = self._reconcile_block(run, p, sh, block, txs, BlockBaseline.from_dict(recorded))
                p["reconcile"][block.name] = path
                if path == "fallback":
                    p["partial_undo"] = True
                self.store.save(run)
            self.ledger.record_written(run["upload_id"], p["label"], _txs(p))
        except Exception as exc:
            p["last_error"] = _error(exc)
            self.store.save(run)
            logger.warning("Run %s: reconciling %s failed; the period stays appending",
                           run["upload_id"], p["label"])
            if isinstance(exc, AUTH_ERRORS):
                raise
            return
        self._mark_written(run, p)

    def _reconcile_block(self, run, p, sh, block, txs, baseline: BlockBaseline) -> str:
        intended = [canonical(intended_cells(tx)) for tx in txs]     # intended[i] is txs[i]
        present = read_block(sh, block)
        cut = baseline.first_write_row - data_start_row()
        positional = digest(present.tuples[:cut]) == baseline.prefix_digest
        # Partition the INDICES of txs, consuming with multiplicity; never a
        # membership test, and never a RowTuple mapped back to a transaction.
        avail = Counter(t for t in (present.tuples[cut:] if positional else present.tuples) if t)
        found_idx = []
        for i, t in enumerate(intended):
            if avail[t] > 0:
                avail[t] -= 1
                found_idx.append(i)
        found = set(found_idx)
        remaining_idx = [i for i in range(len(intended)) if i not in found]
        if len(found_idx) + len(remaining_idx) != len(intended):
            raise RuntimeError("reconcile partition invariant violated")
        pairs = commit_append(sh, block, [txs[i] for i in remaining_idx],
                              context=self._context(run, p), failed_path=self.config.failed_path)
        if positional:
            # Everything at or after first_write_row belongs to this run, so
            # the rows found there are audited too (a crash between write and
            # audit would otherwise leave them un-undoable).
            pairs = pairs + [(strong_key(txs[i]), intended[i]) for i in found_idx]
        # The fallback audits only what it appended: a content match there may
        # be the user's own row, and undo would delete it.
        self.ledger.record_audit(run["upload_id"], sh.id, block.name, pairs)
        logger.info("Run %s: %s %s reconciled (%s): %d found, %d appended", run["upload_id"], p["label"],
                    block.name, "positional" if positional else "fallback", len(found_idx), len(remaining_idx))
        return "positional" if positional else "fallback"

    # ── sorting and cleanup ───────────────────────────────────────────────
    def _closing_sort(self, run: dict) -> None:
        last = run["last_pass"]
        appending = rs.appending_sheet_ids(self.config.runs_dir)
        guard = rs.is_appending_predicate(self.config.runs_dir)
        done = set()
        for label in last["touched"]:
            sh = self._sheets.get(label)
            if sh is None or sh.id in done:
                continue
            done.add(sh.id)
            if sh.id in appending:
                last["unsorted"].append(label)
                continue
            try:
                sort_by_date(sh, is_appending=guard)
            except Exception as exc:
                last["sort_errors"].append(f"{label}: {type(exc).__name__}; /sort {label} retries it")
                if isinstance(exc, AUTH_ERRORS):
                    break

    def _sort_labels(self, labels: List[str]) -> List[str]:
        guard = rs.is_appending_predicate(self.config.runs_dir)
        lines = []
        for label in labels:
            sh = self.registry.lookup(label)
            if sh is None:
                lines.append(f"{label}: not in the index")
                continue
            expenses, income = sort_by_date(sh, is_appending=guard)
            lines.append(f"{label}: sorted ({expenses} expenses, {income} income)")
        return lines

    def _remove_uploads(self, run: dict) -> None:
        folder = run.get("upload_dir")
        if not folder:
            return
        root = os.path.abspath(self.config.uploads_dir)
        folder = os.path.abspath(folder)
        if os.path.commonpath([root, folder]) != root or folder == root:
            return
        shutil.rmtree(folder, ignore_errors=True)
