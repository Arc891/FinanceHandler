"""
The month -> spreadsheet index, data/sheet_index.json.

The bot requests no Drive listing scope (anything beyond drive.file is a
restricted scope and costs a CASA audit), so it cannot find a month's sheet by
searching Drive. This file is therefore **authoritative**: it is the only
record of which spreadsheet holds which financial month, and it cannot be
rebuilt by listing. Back it up with the rest of data/.

Shape:
    {"04/2026": {"id": "<spreadsheet id>", "created_by_bot": false, "created_at": null}}

This module is pure file and value handling. Opening, verifying and creating
sheets is sheet_registry's job (plan 4.4).
"""

import json
import os
import re
import tempfile
from typing import Dict, Optional, Tuple

LABEL_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{4})$")
_URL_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{25,}$")


class IndexConflict(ValueError):
    """A registration would repoint a label or reuse a sheet for a second month."""


def parse_label(label: str) -> Tuple[int, int]:
    """'04/2026' -> (2026, 4). Raises ValueError for anything that is not MM/YYYY."""
    m = LABEL_RE.match(label or "")
    if not m:
        raise ValueError(f"not a month label (MM/YYYY): {label!r}")
    return int(m.group(2)), int(m.group(1))


def label_sort_key(label: str) -> Tuple[int, int]:
    """Chronological key. Never compare labels as strings: '12/2026' > '01/2027'."""
    return parse_label(label)


def extract_spreadsheet_id(url_or_id: str) -> str:
    """Accept a Google Sheets URL or a bare spreadsheet id and return the id."""
    value = (url_or_id or "").strip()
    m = _URL_ID_RE.search(value)
    if m:
        return m.group(1)
    if _BARE_ID_RE.match(value):
        return value
    raise ValueError(f"not a Google Sheets URL or spreadsheet id: {url_or_id!r}")


def load_index(path) -> Dict[str, dict]:
    """Read the index. A missing file is an empty index; a malformed one raises."""
    path = os.fspath(path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object of month labels")
    for label, entry in data.items():
        parse_label(label)
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError(f"{path}: entry {label} has no spreadsheet id")
    return data


def save_index(path, index: Dict[str, dict]) -> None:
    """Write the index atomically, labels in chronological order."""
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    ordered = {label: index[label] for label in sorted(index, key=label_sort_key)}
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".sheet_index.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(ordered, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def register(index: Dict[str, dict], label: str, sheet_id: str, *,
             created_by_bot: bool = False, created_at: Optional[str] = None,
             force: bool = False) -> str:
    """
    Add label -> sheet_id to ``index`` in place.

    Returns 'added', 'unchanged' or 'replaced'. Raises IndexConflict when the
    label already points at another sheet, or the sheet is already registered
    under another label, unless ``force`` is set.
    """
    parse_label(label)
    current = index.get(label)
    if current and current["id"] == sheet_id:
        return "unchanged"
    if not force:
        if current:
            raise IndexConflict(f"{label} is already registered to {current['id']}, not {sheet_id}")
        for other, entry in index.items():
            if entry["id"] == sheet_id:
                raise IndexConflict(f"{sheet_id} is already registered as {other}")
    index[label] = {"id": sheet_id, "created_by_bot": created_by_bot, "created_at": created_at}
    return "replaced" if current else "added"
