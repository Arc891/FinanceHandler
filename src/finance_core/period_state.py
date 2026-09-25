"""
The period anchor file, data/period_state.json (plan 4.3, 4.10).

periods.py is pure; this module is the file around it. The pipeline reads the
anchor at run start, stores the file's full raw JSON as the run's
``anchor_before`` (ledger.start_run), and saves the advanced anchor once the
split has passed its checks. undo_upload.py writes ``anchor_before`` back
verbatim with ``write_state``. A missing file means no anchor.

The file is rebuildable: scripts/seed_state.py derives it from the sheets.
"""

import json
import os
import tempfile
from typing import Optional

from finance_core.config_access import setting
from finance_core.periods import Anchor, anchor_from_state, anchor_to_state

# Plan 4.3 derives these from six months of measured spans (section 11).
DEFAULTS = {
    "PERIOD_BOUNDARY_MARKERS": [r"\bDUO\b", r"Anamata"],
    "PERIOD_BOUNDARY_MIN_AMOUNT": 250.0,
    "PERIOD_MIN_DAYS": 20,          # boundary-to-boundary is 27 to 32 days
    "PERIOD_MAX_DAYS": 35,
    "PERIOD_STEP_DAYS": 29,         # fallback only, beyond the known history
    "PERIOD_LABEL_SPLIT_DAY": 15,
}


def split_settings() -> dict:
    """split_into_periods' keyword arguments from config, minus anchor and force."""
    def get(name):
        return setting(name, DEFAULTS[name])
    return {
        "markers": list(get("PERIOD_BOUNDARY_MARKERS")),
        "min_amount": float(get("PERIOD_BOUNDARY_MIN_AMOUNT")),
        "min_days": int(get("PERIOD_MIN_DAYS")),
        "max_days": int(get("PERIOD_MAX_DAYS")),
        "step_days": int(get("PERIOD_STEP_DAYS")),
        "split_day": int(get("PERIOD_LABEL_SPLIT_DAY")),
    }


def read_state(path) -> Optional[dict]:
    """The file's raw JSON, or None when it does not exist. What anchor_before stores."""
    path = os.fspath(path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc


def write_state(path, state: Optional[dict]) -> None:
    """Write raw state atomically; None removes the file (there was no anchor)."""
    path = os.fspath(path)
    if state is None:
        if os.path.exists(path):
            os.unlink(path)
        return
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".period_state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_anchor(path) -> Optional[Anchor]:
    return anchor_from_state(read_state(path))


def save_anchor(path, anchor: Optional[Anchor]) -> None:
    write_state(path, anchor_to_state(anchor))
