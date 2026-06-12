# Finance Automation Bot - Improvement Plan

**Created**: 2026-01-13
**Status**: Approved by project-scrutinizer
**Last Updated**: 2026-01-13

## Overview

This plan addresses technical debt and critical bugs identified through systematic code review.

---

## Priority 0: Critical Thread Safety Fix (Immediate)

**Problem**: `GoogleSheetsUploadQueue` stores per-user row positions in shared instance variables (`current_expense_row`, `current_income_row`), causing cross-user data corruption when processing concurrent uploads.

**Solution**:
- Create `UserRowPositions` dataclass for per-user isolation
- Add `threading.Lock()` that covers ALL position operations (queue, upload, load, save)
- Remove shared instance variables

**Files to modify**: `src/finance_core/background_upload.py`

**Implementation**:
```python
@dataclass
class UserRowPositions:
    expense_row: int
    income_row: int

class GoogleSheetsUploadQueue:
    def __init__(self, credentials_path: str):
        # ... existing init ...
        self.user_positions: Dict[int, UserRowPositions] = {}
        self._position_lock = threading.Lock()

    def queue_transaction(self, transaction, transaction_type, user_id):
        # Lock covers ENTIRE read-increment-write sequence
        with self._position_lock:
            positions = self._get_or_load_user_positions(user_id)
            if transaction_type == "expense":
                reserved_row = positions.expense_row
                positions.expense_row += 1
            else:
                reserved_row = positions.income_row
                positions.income_row += 1
            self._save_row_positions_unlocked(user_id, positions)
```

**Validation**: Test script with two threads calling `queue_transaction()` 100 times each

---

## Priority 1: Atomic File Operations

**Problem**: JSON files use read-modify-write pattern without locking, risking data corruption.

**Solution**: Create `src/finance_core/file_storage.py`:

```python
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager

@contextmanager
def atomic_json_update(path: str, default=None):
    """Atomic read-modify-write for JSON files with temp-file-and-rename."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        with open(path, 'w') as f:
            json.dump(default or {}, f)

    with open(path, 'r+', encoding='utf-8') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            data = json.load(f)
            yield data
            # Write to temp file first
            dir_path = os.path.dirname(path)
            with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False) as tmp:
                json.dump(data, tmp, indent=2)
                tmp_path = tmp.name
            os.replace(tmp_path, path)  # Atomic on POSIX
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**Files to refactor**:
- `session_management.py`: `save_session()`, `cache_transaction()`, `remove_cached_transaction()`, `update_cached_transaction_row()`, `save_sheet_positions()`, `add_auto_categorized_transaction()`
- `pending_transactions.py`: `add_pending_transaction()`, `update_pending_status()`, `set_message_id()`, `clear_user_pending()`
- `background_upload.py`: `save_failed_upload()`, `clear_failed_uploads()`

---

## Priority 2: Documentation Updates

**Status**: ✅ COMPLETED (2026-01-13)

**Changes made to CLAUDE.md**:
1. Fixed retry script path: `python scripts/retry_failed_transactions.py <user_id>`
2. Added Failed Upload Recovery section with full explanation
3. Added Discord Commands table with all 8 commands including `/pending`
4. Documented CSV normalization behavior (files modified in-place)
5. Added `failed_uploads.json` to directory structure

---

## Priority 3: Code Quality

### 3.1 Exception Handling Cleanup

Replace 13 `except BaseException: pass` with context-specific exceptions:

| Location | Context | Replacement |
|----------|---------|-------------|
| `bot_commands.py:351` | Message delete | `except discord.NotFound: pass` |
| `transaction_prompt.py:112` | Message delete | `except discord.NotFound: pass` |
| `transaction_prompt.py:457` | Message delete | `except discord.NotFound: pass` |
| `transaction_prompt.py:561` | Message delete | `except discord.NotFound: pass` |
| `discord_notifier.py:128` | Message edit | `except discord.HTTPException: pass` |
| `discord_notifier.py:144` | Message edit | `except discord.HTTPException: pass` |
| `discord_notifier.py:175` | User fetch | `except discord.HTTPException: user = None` |
| `export.py:120` | Message edit | `except discord.HTTPException: pass` |
| `export.py:351` | Date parse | `except (ValueError, TypeError): return datetime(1970, 1, 1)` |
| `export.py:402` | Date parse | `except (ValueError, TypeError): return datetime(1970, 1, 1)` |
| `export.py:423` | Message send | `except discord.HTTPException: pass` |
| `export.py:435` | Message send | `except discord.HTTPException: pass` |
| `automation_endpoints.py:267` | Line count | `except (IOError, OSError): pass` |

### 3.2 Magic Numbers to Config

Add to `config_settings.py`:
```python
# API Rate Limiting
SHEETS_API_RATE_LIMIT_SECONDS = 2.0
SHEETS_MAX_SCAN_ROWS = 500
MIN_DATA_ROWS_FOR_VALID_CACHE = 3

# UI Timeouts
UI_VIEW_TIMEOUT_SECONDS = 300
```

---

## Explicitly NOT Doing

1. **CSV preservation change** - Document current behavior instead (files are modified in-place)
2. **UI base class extraction** - Risk of regression outweighs DRY benefit
3. **Circular import cleanup** - Function-level imports are intentional pattern
4. **SQLite migration** - Overkill for single-user personal project
5. **Comprehensive test suite** - Targeted tests for critical paths only

---

## Backlog

1. Add rate limiting to `_detect_current_positions()` API calls
2. Session cleanup logic (measure sizes first before implementing limits)
3. Orphaned cached transaction reconciliation
