"""
The pipeline's run state files, data/runs/<upload_id>.json (plan 4.7).

A run file holds the rows of every period that is not yet `written`, so it is
the only place an accepted-but-unwritten row lives. ``RunStore`` writes it
atomically after every status transition; ``appending_sheet_ids`` answers the
one question a compaction must ask first: is a period writing to this
spreadsheet still `appending`?

Period statuses: split, resolved, categorised, appending, written, failed
(with ``failed_reason``). A run is open while ``closed`` is None; it closes as
"complete", "abandoned" (/cancel) or "refused" (the split was rejected).
"""

import glob
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Callable, List, Optional, Set, Tuple

from finance_core.config_access import project_path, setting


def runs_dir() -> str:
    return project_path(setting("RUNS_DIR", "data/runs"))


def appending_sheet_ids(directory=None) -> Set[str]:
    """
    Spreadsheet ids with a period at `appending` in any run file.

    An unreadable run file raises rather than being skipped: it may be the one
    holding the `appending` period, and guessing wrong lets a compaction destroy
    that period's baseline.
    """
    found = set()
    for path in sorted(glob.glob(os.path.join(os.fspath(directory or runs_dir()), "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ValueError(f"unreadable run state {path}: {exc}") from exc
        for period in data.get("periods", []):
            if period.get("status") == "appending" and period.get("sheet_id"):
                found.add(period["sheet_id"])
    return found


def is_appending_predicate(directory=None) -> Callable[[str], bool]:
    """A predicate for sheet_writer's compaction guard, read fresh on every call."""
    return lambda sheet_id: sheet_id in appending_sheet_ids(directory)


SPLIT, RESOLVED, CATEGORISED, APPENDING, WRITTEN, FAILED = (
    "split", "resolved", "categorised", "appending", "written", "failed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_period(label: str, expenses: list, income: list) -> dict:
    return {
        "label": label, "sheet_id": None, "status": SPLIT, "failed_reason": None,
        "rows": {"expenses": expenses, "income": income},
        "categorised": False, "baseline": {}, "flagged": [], "last_error": None,
        "created": False, "notes": [], "reconcile": {}, "partial_undo": False,
        "not_started": None,
        "counts": {"rows": len(expenses) + len(income), "expenses": len(expenses),
                   "income": len(income), "flagged": 0},
    }


class RunStore:
    """data/runs/: one JSON file per upload_id, each written whole and atomically."""

    def __init__(self, directory=None):
        self.directory = os.fspath(directory or runs_dir())

    def path(self, upload_id: str) -> str:
        return os.path.join(self.directory, f"{upload_id}.json")

    def create(self, upload_id: str, *, files, force: bool, upload_dir: Optional[str],
               anchor_before, note: Optional[str] = None) -> dict:
        if os.path.exists(self.path(upload_id)):
            raise ValueError(f"run {upload_id} already exists")
        run = {
            "upload_id": upload_id, "files": list(files), "upload_dir": upload_dir,
            "force": bool(force), "note": note or None, "started_at": _now(), "anchor_before": anchor_before,
            "anchor_after": None, "anchor_saved": False, "split_done": False,
            "closed": None, "closed_at": None, "stopped": None, "notes": {}, "periods": [],
        }
        self.save(run)
        return run

    def load(self, upload_id: str) -> dict:
        with open(self.path(upload_id), encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, run: dict) -> None:
        os.makedirs(self.directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".run.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(run, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path(run["upload_id"]))
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def close(self, run: dict, how: str) -> None:
        run["closed"] = how
        run["closed_at"] = _now()
        self.save(run)

    def all_runs(self) -> List[dict]:
        """Every run, oldest first. An unreadable file raises, as appending_sheet_ids does."""
        runs = []
        for path in glob.glob(os.path.join(self.directory, "*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    runs.append(json.load(fh))
            except (OSError, ValueError) as exc:
                raise ValueError(f"unreadable run state {path}: {exc}") from exc
        return sorted(runs, key=lambda r: (r.get("started_at") or "", r.get("upload_id") or ""))

    def open_runs(self) -> List[dict]:
        return [r for r in self.all_runs() if r.get("closed") is None]

    def appending_periods(self) -> List[Tuple[str, str, str]]:
        """(upload_id, label, sheet_id) of every period at `appending`, in any run."""
        return [(r["upload_id"], p["label"], p.get("sheet_id"))
                for r in self.all_runs() for p in r.get("periods", [])
                if p.get("status") == APPENDING]
