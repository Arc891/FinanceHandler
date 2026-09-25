"""
Read-only view of the pipeline's run state files, data/runs/<upload_id>.json (plan 4.7).

Phase 1 needs one question answered before anything compacts a block: is a
period writing to this spreadsheet still `appending`? The run state itself is
written by the pipeline (Phase 3), which extends this module.
"""

import glob
import json
import os
from typing import Callable, Set

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
