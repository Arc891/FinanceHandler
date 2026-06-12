"""
Background Google Sheets upload queue with throttling.
Handles immediate transaction uploads with proper rate limiting.
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime
import threading
import time
from queue import Queue, Empty
import os
import json

from finance_core.google_sheets import GoogleSheetsExporter

logger = logging.getLogger(__name__)


def _get_failed_uploads_path() -> str:
    """Get the path to the failed uploads recovery file"""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, "data", "failed_uploads.json")


def _load_failed_uploads() -> Dict[str, List[Dict[str, Any]]]:
    """Load failed uploads from recovery file"""
    path = _get_failed_uploads_path()
    if not os.path.exists(path):
        return {"failed": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"⚠️ Could not load failed uploads file: {e}")
        return {"failed": []}


def _save_failed_uploads(data: Dict[str, List[Dict[str, Any]]]) -> None:
    """Save failed uploads to recovery file"""
    path = _get_failed_uploads_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_failed_upload(transaction: Dict[str, Any], transaction_type: str,
                       user_id: int, error: str) -> None:
    """Save a failed upload to the recovery file for later retry"""
    data = _load_failed_uploads()

    failed_item = {
        "transaction": transaction,
        "transaction_type": transaction_type,
        "user_id": user_id,
        "error": error,
        "failed_at": datetime.now().isoformat()
    }

    data["failed"].append(failed_item)
    _save_failed_uploads(data)
    logger.info(f"💾 Saved failed upload to recovery file for user {user_id}")


def get_failed_uploads(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get failed uploads, optionally filtered by user_id"""
    data = _load_failed_uploads()
    failed = data.get("failed", [])

    if user_id is not None:
        return [f for f in failed if f.get("user_id") == user_id]
    return failed


def clear_failed_uploads(user_id: Optional[int] = None) -> int:
    """Clear failed uploads, optionally filtered by user_id. Returns count cleared."""
    data = _load_failed_uploads()
    original_count = len(data.get("failed", []))

    if user_id is not None:
        data["failed"] = [f for f in data.get("failed", []) if f.get("user_id") != user_id]
    else:
        data["failed"] = []

    _save_failed_uploads(data)
    cleared = original_count - len(data["failed"])
    logger.info(f"🧹 Cleared {cleared} failed uploads from recovery file")
    return cleared


@dataclass
class TransactionUpload:
    """Represents a transaction to be uploaded to Google Sheets"""
    transaction: Dict[str, Any]
    transaction_type: str  # "income" or "expense"
    user_id: int
    timestamp: datetime


@dataclass
class CachedTransactionReplacement:
    """Represents a replacement of a cached transaction"""
    cache_id: str
    new_transaction: Dict[str, Any]
    transaction_type: str
    user_id: int
    timestamp: datetime


class GoogleSheetsUploadQueue:
    """
    Background queue for uploading transactions to Google Sheets with rate limiting.

    Google Sheets API limits:
    - 100 requests per 100 seconds per user
    - 500 requests per 100 seconds per project

    We'll be conservative and use 1 request per 2 seconds to stay well within limits.
    """

    # Positions older than this are considered stale and will be re-detected
    POSITION_STALENESS_SECONDS = 30 * 60  # 30 minutes

    def __init__(self, credentials_path: str):
        self.credentials_path = credentials_path
        self.upload_queue = Queue()
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.exporter: Optional[GoogleSheetsExporter] = None

        # Load configurable starting rows
        try:
            from config.config_settings import GSHEET_EXPENSE_START_ROW, GSHEET_INCOME_START_ROW
            self.default_expense_start_row = GSHEET_EXPENSE_START_ROW
            self.default_income_start_row = GSHEET_INCOME_START_ROW
        except ImportError:
            # Fallback to safe defaults if config not available
            self.default_expense_start_row = 2
            self.default_income_start_row = 2

        # Lock protecting shared mutable state (row positions, user_id, staleness timestamp)
        self._position_lock = threading.Lock()

        # Track row positions - will be loaded per user when needed
        self.current_expense_row = self.default_expense_start_row  # Use configurable default
        self.current_income_row = self.default_income_start_row
        self.current_user_id = None  # Track which user's positions we have loaded
        self._last_position_load: Optional[datetime] = None  # When positions were last loaded

        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 2.0  # 2 seconds between requests

    def _positions_may_be_stale(self) -> bool:
        """Check if loaded positions are potentially stale based on time elapsed"""
        if self._last_position_load is None:
            return True
        elapsed = (datetime.now() - self._last_position_load).total_seconds()
        return elapsed > self.POSITION_STALENESS_SECONDS

    def _load_row_positions(self, user_id: int):
        """Load the current row positions for a specific user"""
        from finance_core.session_management import get_sheet_positions

        try:
            from config.config_settings import GSHEET_NAME
        except ImportError:
            GSHEET_NAME = None

        try:
            positions = get_sheet_positions(user_id)
            self.current_expense_row = positions.get(
                'expense_row', self.default_expense_start_row)
            self.current_income_row = positions.get(
                'income_row', self.default_income_start_row)

            # Handle None values that might be stored in the session
            if self.current_expense_row is None:
                self.current_expense_row = self.default_expense_start_row
            if self.current_income_row is None:
                self.current_income_row = self.default_income_start_row

            self.current_user_id = user_id
            logger.info(
                f"📍 Loaded row positions for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")

            # Check if positions were saved for a different sheet (e.g. after config change + restart)
            saved_sheet = positions.get('sheet_name')
            if saved_sheet and GSHEET_NAME and saved_sheet != GSHEET_NAME:
                logger.warning(
                    f"⚠️ Saved positions are for sheet '{saved_sheet}' but current sheet is '{GSHEET_NAME}' - forcing fresh detection")
                self._detect_current_positions(user_id)
            elif positions.get('last_updated') is None:
                # If no positions saved yet, detect them
                self._detect_current_positions(user_id)
            else:
                # If cached positions are very high (>10), verify the sheet actually has that much data
                # This prevents using stale positions when the sheet was cleared
                # Only do this check if we have valid numeric values
                if (self.current_expense_row and self.current_expense_row > 10) or (
                        self.current_income_row and self.current_income_row > 10):
                    logger.info(
                        f"🔍 Cached positions seem high (exp:{self.current_expense_row}, inc:{self.current_income_row}), verifying with sheet...")

                    # Quick check to see if sheet actually has data at those
                    # positions
                    if not self.exporter:
                        self.exporter = GoogleSheetsExporter(
                            self.credentials_path)
                    sheet = self.exporter._get_worksheet()

                    # Check if there's actually data near the cached positions
                    try:
                        check_range = f"B{max(1, self.current_expense_row-5)}:J{self.current_expense_row}"
                        check_data = sheet.get(check_range)

                        # Count non-empty rows
                        data_rows = 0
                        if check_data:
                            for row in check_data:
                                if any(str(cell).strip()
                                       for cell in row if cell):
                                    data_rows += 1

                        if data_rows < 3:  # If less than 3 rows of data found, sheet is likely empty
                            logger.warning(
                                f"⚠️ Cached positions point to mostly empty area ({data_rows} data rows found)")
                            logger.warning(
                                "⚠️ Sheet may have been cleared - forcing fresh detection")
                            self._detect_current_positions(user_id)
                        else:
                            logger.info(
                                f"✅ Sheet has {data_rows} data rows, cached positions seem valid")
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Could not verify cached positions: {e}, forcing fresh detection")
                        self._detect_current_positions(user_id)

            self._last_position_load = datetime.now()

        except Exception as e:
            logger.error(f"❌ Error loading row positions: {e}")
            self._detect_current_positions(user_id)

    def _save_row_positions(self, user_id: int):
        """Save current row positions for a specific user"""
        from finance_core.session_management import save_sheet_positions

        try:
            from config.config_settings import GSHEET_NAME
        except ImportError:
            GSHEET_NAME = None

        try:
            save_sheet_positions(
                user_id,
                self.current_expense_row,
                self.current_income_row,
                sheet_name=GSHEET_NAME)
            logger.debug(
                f"💾 Saved row positions for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")
        except Exception as e:
            logger.error(f"❌ Error saving row positions: {e}")

    def _detect_current_positions(self, user_id: int):
        """Detect current last row positions in the Google Sheet for a specific user"""
        try:
            if not self.exporter:
                self.exporter = GoogleSheetsExporter(self.credentials_path)

            sheet = self.exporter._get_worksheet()

            logger.info(
                f"🔍 Detecting row positions in Google Sheet for user {user_id}...")

            # Get expense columns (B:E)
            expense_values = sheet.get('B1:E1000')
            self.current_expense_row = self._find_last_data_row(
                expense_values, "expense")

            # Get income columns (G:J)
            income_values = sheet.get('G1:J1000')
            self.current_income_row = self._find_last_data_row(
                income_values, "income")

            # Ensure we start at least at the configured starting rows
            self.current_expense_row = max(
                self.current_expense_row,
                self.default_expense_start_row)
            self.current_income_row = max(
                self.current_income_row,
                self.default_income_start_row)

            logger.info(
                f"🔍 Detected row positions for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")
            self._save_row_positions(user_id)

        except Exception as e:
            logger.error(f"❌ Error detecting row positions: {e}")
            # Fallback to safe defaults
            self.current_expense_row = self.default_expense_start_row
            self.current_income_row = self.default_income_start_row

    def _find_last_data_row(self, values, column_type="expense"):
        """Find the last row that contains actual data

        Args:
            values: Sheet values to analyze
            column_type: "expense" or "income" to determine minimum starting row
        """
        if not values:
            min_start_row = self.default_expense_start_row if column_type == "expense" else self.default_income_start_row
            return min_start_row

        # Determine minimum starting row based on configuration
        min_start_row = self.default_expense_start_row if column_type == "expense" else self.default_income_start_row

        last_data_row = 0
        for i, row in enumerate(values):
            # Check if any cell in this row has non-empty, non-whitespace
            # content
            has_data = False
            for cell in row:
                cell_str = str(cell).strip() if cell else ""
                if cell_str:
                    has_data = True
                    break

            if has_data:
                last_data_row = i + 1  # Convert to 1-based row number

        # Return the next available row (last data row + 1), but ensure it's at
        # least the configured starting row
        next_row = max(last_data_row + 1, min_start_row)
        return next_row

    def start(self):
        """Start the background upload thread"""
        if self.is_running:
            logger.warning("⚠️ Upload queue already running")
            return

        self.is_running = True
        self.thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.thread.start()
        logger.info("🚀 Google Sheets upload queue started")

    def stop(self):
        """Stop the background upload thread"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("🛑 Google Sheets upload queue stopped")

    def queue_transaction(
            self, transaction: Dict[str, Any], transaction_type: str, user_id: int):
        """Queue a transaction for upload to Google Sheets"""
        upload = TransactionUpload(
            transaction=transaction,
            transaction_type=transaction_type,
            user_id=user_id,
            timestamp=datetime.now()
        )

        # For cached transactions (dummy uploads), immediately reserve the row position
        # to prevent multiple cached transactions from using the same row
        # Skip this for replacements since they use existing rows
        if 'cache_id' in transaction and not transaction.get(
                '_is_replacement'):
            with self._position_lock:
                # Ensure we have positions loaded for this user
                if self.current_user_id != user_id:
                    self._load_row_positions(user_id)

                # Reserve the row position immediately
                if transaction_type == "expense":
                    reserved_row = self.current_expense_row
                    self.current_expense_row += 1
                else:  # income
                    reserved_row = self.current_income_row
                    self.current_income_row += 1

                # Save the updated positions to prevent conflicts
                self._save_row_positions(user_id)

            # Store the reserved row in the cached transaction
            from finance_core.session_management import update_cached_transaction_row
            update_cached_transaction_row(
                user_id, transaction['cache_id'], reserved_row)

            logger.info(
                f"📍 Reserved row {reserved_row} for cached transaction {transaction['cache_id']} ({transaction_type})")

        self.upload_queue.put(upload)

        upload_type = "replacement" if transaction.get(
            '_is_replacement') else "upload"
        cache_info = f" (cache_id: {transaction.get('cache_id', 'N/A')})"
        logger.debug(
            f"📝 Queued {transaction_type} transaction for {upload_type} (queue size: {self.upload_queue.qsize()}){cache_info}")

    def queue_cached_replacement(
            self, cache_id: str, new_transaction: Dict[str, Any], transaction_type: str, user_id: int):
        """Queue a cached transaction replacement"""
        # Add the cache_id and replacement flag to the transaction
        # Preserve any existing fields like _reserved_row
        new_transaction_with_cache = {
            **new_transaction,
            "cache_id": cache_id,
            "_is_replacement": True}
        self.queue_transaction(
            new_transaction_with_cache,
            transaction_type,
            user_id)
        logger.info(
            f"🔄 Queued replacement for cached transaction {cache_id} (reserved_row: {new_transaction.get('_reserved_row', 'N/A')})")

    def _rate_limit(self):
        """Ensure we don't exceed rate limits"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            logger.debug(f"⏰ Rate limiting: sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _upload_worker(self):
        """Background worker that processes the upload queue"""
        logger.info("👷 Upload worker started")

        while self.is_running:
            try:
                # Get next item from queue (wait up to 1 second)
                upload = self.upload_queue.get(timeout=1.0)

                # Apply rate limiting
                self._rate_limit()

                # Upload with retry on transient errors (429 rate limits)
                self._upload_with_retry(upload)

                # Mark task as done
                self.upload_queue.task_done()

            except Empty:
                # No items in queue, continue
                continue
            except Exception as e:
                logger.error(f"❌ Error in upload worker: {e}")
                # Continue running even if individual uploads fail
                continue

        logger.info("👷 Upload worker stopped")

    def _upload_with_retry(self, upload: TransactionUpload, max_retries: int = 3):
        """Upload a transaction with exponential backoff retry on rate limit errors"""
        for attempt in range(max_retries + 1):
            try:
                self._upload_single_transaction(upload)
                return  # Success
            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "Quota exceeded" in error_str

                if is_rate_limit and attempt < max_retries:
                    backoff = 2 ** attempt * 30  # 30s, 60s, 120s
                    logger.warning(
                        f"⏳ Rate limited (attempt {attempt + 1}/{max_retries + 1}), "
                        f"backing off {backoff}s before retry...")
                    time.sleep(backoff)
                    # Clear cached sheet to force fresh connection after backoff
                    if self.exporter:
                        self.exporter.sheet = None
                    continue
                else:
                    raise  # Non-retryable error or max retries exceeded

    def _upload_single_transaction(self, upload: TransactionUpload):
        """Upload a single transaction to Google Sheets"""
        try:
            # Ensure we have fresh positions loaded for this user
            with self._position_lock:
                needs_refresh = self.current_user_id != upload.user_id
                if not needs_refresh and self._positions_may_be_stale():
                    logger.info("⏰ Row positions may be stale (>30min old), refreshing...")
                    needs_refresh = True
                if needs_refresh:
                    self._load_row_positions(upload.user_id)

            if not self.exporter:
                self.exporter = GoogleSheetsExporter(self.credentials_path)

            # Try to get the worksheet
            sheet = self.exporter._get_worksheet()

            # Format transaction for sheet
            formatted_data = self.exporter.format_transaction_for_sheet(
                upload.transaction)

            # For cached transactions, check if row was already reserved during
            # queuing
            target_row = None
            use_reserved_row = False

            if 'cache_id' in upload.transaction:
                # Check if this is a replacement with a pre-stored reserved row
                if upload.transaction.get(
                        '_is_replacement') and upload.transaction.get('_reserved_row'):
                    target_row = upload.transaction['_reserved_row']
                    use_reserved_row = True
                    logger.info(
                        f"🔄 Using pre-stored reserved row {target_row} for replacement of cached transaction {upload.transaction['cache_id']}")
                else:
                    # For non-replacements, look up the cached transaction to
                    # get the reserved row
                    from finance_core.session_management import get_cached_transactions
                    cached_transactions = get_cached_transactions(
                        upload.user_id)

                    for cached_tx in cached_transactions:
                        if cached_tx["cache_id"] == upload.transaction['cache_id']:
                            logger.debug(
                                f"🔍 Found cached transaction {upload.transaction['cache_id']} for user {upload.user_id}")
                            reserved_row = cached_tx.get("sheet_row")
                            if reserved_row:
                                target_row = reserved_row
                                use_reserved_row = True
                                logger.info(
                                    f"🎯 Using pre-reserved row {target_row} for cached transaction {upload.transaction['cache_id']}")
                                break

            # If no reserved row, use current positions (only for
            # non-replacements)
            if not target_row:
                if upload.transaction.get('_is_replacement'):
                    logger.error(
                        "🚨 CRITICAL: Replacement transaction has no reserved row!",
                        extra={
                            "cache_id": upload.transaction.get("cache_id"),
                            "transaction_details": upload.transaction,
                        }
                    )
                    return  # Abort replacement to prevent data corruption

                if upload.transaction_type == "expense":
                    target_row = self.current_expense_row
                else:  # income
                    target_row = self.current_income_row
                logger.info(
                    f"📍 Using current row {target_row} for {upload.transaction_type} transaction")

            # CRITICAL: Check if the target row exceeds sheet bounds and expand
            # if necessary. Use cached sheet metadata to avoid extra API calls;
            # if the cache is wrong, ensure_sheet_capacity will refresh anyway.
            try:
                if not self.exporter.check_row_bounds(target_row, use_cache=True):
                    logger.warning(
                        f"⚠️ Target row {target_row} exceeds sheet bounds, expanding sheet...")
                    self.exporter.ensure_sheet_capacity(
                        target_row, buffer_rows=50)
                    logger.info(
                        f"✅ Sheet expanded to accommodate row {target_row}")
            except Exception as e:
                logger.error(
                    f"❌ Failed to expand sheet for row {target_row}: {e}")
                raise Exception(
                    f"Cannot upload to row {target_row}: sheet expansion failed: {e}")

            # Determine target range based on transaction type
            if upload.transaction_type == "expense":
                target_range = f"B{target_row}:E{target_row}"
                check_range = f"B{target_row}:E{target_row}"
            else:  # income
                target_range = f"G{target_row}:J{target_row}"
                check_range = f"G{target_row}:J{target_row}"

            # SAFETY CHECK: Verify target row is empty before uploading
            # Skip safety check for replacements and pre-reserved rows (they
            # should be safe by design)
            if not use_reserved_row and not upload.transaction.get(
                    '_is_replacement'):
                try:
                    existing_data = sheet.get(check_range)
                    if existing_data and existing_data[0]:
                        # Check if any cell has content
                        has_content = any(str(cell).strip()
                                          for cell in existing_data[0] if cell)
                        if has_content:
                            logger.error(
                                f"🚨 CRITICAL: Target row {target_row} already contains data: {existing_data[0]}")
                            logger.error(
                                "🚨 This would overwrite existing data! Recalculating row position.")

                            # Re-detect the actual next empty row from scratch
                            if upload.transaction_type == "expense":
                                expense_values = sheet.get('B1:E1000')
                                corrected_row = self._find_last_data_row(
                                    expense_values, "expense")
                                self.current_expense_row = corrected_row
                                target_row = corrected_row
                                target_range = f"B{target_row}:E{target_row}"
                            else:
                                income_values = sheet.get('G1:J1000')
                                corrected_row = self._find_last_data_row(
                                    income_values, "income")
                                self.current_income_row = corrected_row
                                target_row = corrected_row
                                target_range = f"G{target_row}:J{target_row}"

                            # Double-check the corrected row is actually empty
                            check_range = target_range
                            double_check = sheet.get(check_range)
                            if double_check and double_check[0]:
                                double_check_content = any(
                                    str(cell).strip() for cell in double_check[0] if cell)
                                if double_check_content:
                                    logger.error(
                                        f"🚨 Cannot safely upload - even corrected row {target_row} has data")
                                    return  # Abort upload to prevent overwriting
                except Exception as e:
                    logger.warning(
                        f"⚠️ Could not verify target row emptiness: {e}")

            # Upload to sheet
            try:
                sheet.update([formatted_data], target_range)
            except Exception as e:
                logger.error(
                    f"❌ Failed to upload to range {target_range}: {e}")
                raise

            # Handle cached transaction logic
            if 'cache_id' in upload.transaction:
                if upload.transaction.get('_is_replacement'):
                    # This is a replacement - try to remove the cached transaction from session
                    # (it might already be removed by the UI, which is fine)
                    try:
                        from finance_core.session_management import remove_cached_transaction
                        remove_cached_transaction(
                            upload.user_id, upload.transaction['cache_id'])
                        logger.info(
                            f"🔄 Replaced cached dummy and removed {upload.transaction['cache_id']} from cache")
                    except Exception as e:
                        logger.debug(
                            f"ℹ️ Cached transaction {upload.transaction['cache_id']} already removed from session: {e}")
                elif not use_reserved_row:
                    # This is a new dummy cache - store the row for future
                    # replacement
                    from finance_core.session_management import update_cached_transaction_row
                    update_cached_transaction_row(
                        upload.user_id, upload.transaction['cache_id'], target_row)
                    logger.info(
                        f"📍 Stored sheet row {target_row} for cached transaction {upload.transaction['cache_id']}")

            # Update row position after successful upload (only for
            # non-reserved rows and non-replacements)
            if not use_reserved_row and not upload.transaction.get(
                    '_is_replacement'):
                if upload.transaction_type == "expense":
                    self.current_expense_row = target_row + 1
                else:
                    self.current_income_row = target_row + 1

                # Save updated positions
                self._save_row_positions(upload.user_id)
                logger.debug(
                    f"📍 Updated current positions: expense={self.current_expense_row}, income={self.current_income_row}")

            logger.info(
                f"✅ Uploaded {upload.transaction_type} to {target_range}: {formatted_data[2][:50]}...")

        except Exception as e:
            error_str = str(e)
            # Reset state on grid limits errors so subsequent transactions can self-correct
            if "exceeds grid limits" in error_str.lower():
                logger.warning("⚠️ Grid limits error - resetting sheet cache and forcing position reload")
                with self._position_lock:
                    if self.exporter:
                        self.exporter.sheet = None
                    self.current_user_id = None  # Force position reload on next attempt
                    self._last_position_load = None

            logger.error(f"❌ Failed to upload transaction: {e}")
            # Save to recovery file for later retry
            save_failed_upload(
                transaction=upload.transaction,
                transaction_type=upload.transaction_type,
                user_id=upload.user_id,
                error=error_str
            )
            raise

    def retry_failed_transactions(
            self, user_id: int, transaction_type: Optional[str] = None):
        """
        Retry failed transactions from BOTH the recovery file AND session data.

        Args:
            user_id: The user ID to retry transactions for
            transaction_type: Optional filter for "expense" or "income", or None for both
        """
        try:
            retry_count = 0

            # First, check the failed uploads recovery file
            failed_uploads = get_failed_uploads(user_id)
            if failed_uploads:
                logger.info(
                    f"🔄 Found {len(failed_uploads)} failed uploads in recovery file for user {user_id}")
                for item in failed_uploads:
                    tx_type = item.get("transaction_type")
                    if transaction_type is not None and tx_type != transaction_type:
                        continue

                    transaction = item.get("transaction", {})
                    if not transaction.get("category"):
                        logger.warning(
                            f"⚠️ Skipping transaction without category: {transaction.get('booking_date', 'Unknown')}")
                        continue

                    self.queue_transaction(transaction, tx_type, user_id)
                    retry_count += 1
                    logger.debug(
                        f"🔄 Queued from recovery: {transaction.get('description', 'No description')[:50]}")

            # Also check session data (legacy support)
            from finance_core.session_management import load_session
            remaining, income_transactions, expense_transactions = load_session(
                user_id)

            # Retry expense transactions from session
            if transaction_type in (None, "expense") and expense_transactions:
                logger.info(
                    f"🔄 Retrying {len(expense_transactions)} expense transactions from session for user {user_id}")
                for transaction in expense_transactions:
                    if not transaction.get("category"):
                        logger.warning(
                            f"⚠️ Skipping expense without category: {transaction.get('booking_date', 'Unknown')}")
                        continue

                    self.queue_transaction(transaction, "expense", user_id)
                    retry_count += 1
                    logger.debug(
                        f"🔄 Queued from session: {transaction.get('description', 'No description')[:50]}")

            # Retry income transactions from session
            if transaction_type in (None, "income") and income_transactions:
                logger.info(
                    f"🔄 Retrying {len(income_transactions)} income transactions from session for user {user_id}")
                for transaction in income_transactions:
                    if not transaction.get("category"):
                        logger.warning(
                            f"⚠️ Skipping income without category: {transaction.get('booking_date', 'Unknown')}")
                        continue

                    self.queue_transaction(transaction, "income", user_id)
                    retry_count += 1
                    logger.debug(
                        f"🔄 Queued from session: {transaction.get('description', 'No description')[:50]}")

            if retry_count > 0:
                logger.info(
                    f"✅ Queued {retry_count} failed transactions for retry (user {user_id})")
            else:
                logger.info(
                    f"ℹ️ No failed transactions found to retry for user {user_id}")

            return retry_count

        except Exception as e:
            logger.error(
                f"❌ Error retrying failed transactions for user {user_id}: {e}")
            raise

    def clear_failed_transactions_after_retry(self, user_id: int):
        """
        Clear the categorized transactions from session AND recovery file after successful retry.
        This should be called after confirming the retry uploads were successful.
        """
        try:
            from finance_core.session_management import save_session, load_session

            # Clear from recovery file first
            recovery_cleared = clear_failed_uploads(user_id)

            # Load current session
            remaining, income_transactions, expense_transactions = load_session(
                user_id)

            # Clear the categorized transactions but keep remaining
            # uncategorized ones
            save_session(user_id, remaining, [], [])

            session_cleared = len(income_transactions) + len(expense_transactions)
            total_cleared = recovery_cleared + session_cleared
            logger.info(
                f"🧹 Cleared {total_cleared} transactions after retry (user {user_id}): "
                f"{recovery_cleared} from recovery file, {session_cleared} from session")

        except Exception as e:
            logger.error(
                f"❌ Error clearing failed transactions after retry: {e}")
            raise

    def reset_row_positions(self, user_id: int):
        """Force a complete reset and re-detection of row positions from the Google Sheet"""
        logger.warning(
            f"🔄 Forcing complete reset of row positions for user {user_id}...")

        # Clear cached positions
        self.current_expense_row = self.default_expense_start_row
        self.current_income_row = self.default_income_start_row
        self.current_user_id = None

        # Force re-detection
        self._detect_current_positions(user_id)

        logger.info(
            f"✅ Row positions reset and re-detected for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")


# Global instance
_upload_queue: Optional[GoogleSheetsUploadQueue] = None


def get_upload_queue() -> GoogleSheetsUploadQueue:
    """Get the global upload queue instance"""
    global _upload_queue
    if _upload_queue is None:
        try:
            from config.config_settings import GOOGLE_CREDENTIALS_PATH
            credentials_path = GOOGLE_CREDENTIALS_PATH
        except ImportError:
            # Fallback to default path
            base_dir = os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)))
            credentials_path = os.path.join(
                base_dir, "config", "google_service_account.json")

        _upload_queue = GoogleSheetsUploadQueue(credentials_path)
    return _upload_queue


def start_upload_queue():
    """Start the global upload queue"""
    queue = get_upload_queue()
    queue.start()


def stop_upload_queue():
    """Stop the global upload queue"""
    if _upload_queue:
        _upload_queue.stop()


def queue_transaction_upload(
        transaction: Dict[str, Any], transaction_type: str, user_id: int):
    """Queue a transaction for background upload to Google Sheets"""
    queue = get_upload_queue()
    queue.queue_transaction(transaction, transaction_type, user_id)


def queue_cached_replacement(
        cache_id: str, new_transaction: Dict[str, Any], transaction_type: str, user_id: int):
    """Queue a cached transaction replacement"""
    queue = get_upload_queue()
    queue.queue_cached_replacement(
        cache_id,
        new_transaction,
        transaction_type,
        user_id)


def retry_failed_transactions(
        user_id: int, transaction_type: Optional[str] = None) -> int:
    """
    Retry failed transactions from the user's session data.

    Args:
        user_id: The user ID to retry transactions for
        transaction_type: Optional filter for "expense" or "income", or None for both

    Returns:
        Number of transactions queued for retry
    """
    queue = get_upload_queue()
    return queue.retry_failed_transactions(user_id, transaction_type)


def clear_failed_transactions_after_retry(user_id: int):
    """
    Clear the categorized transactions from session after successful retry.
    This should be called after confirming the retry uploads were successful.
    """
    queue = get_upload_queue()
    queue.clear_failed_transactions_after_retry(user_id)


def sort_sheet_after_uploads(timeout: float = 60.0) -> bool:
    """
    Wait for the upload queue to empty, then sort the Google Sheet by date.

    This should be called after queueing a batch of transactions to ensure
    the sheet is sorted once all uploads are complete.

    Args:
        timeout: Maximum time to wait for queue to empty (in seconds)

    Returns:
        True if sort was successful, False otherwise
    """
    queue = get_upload_queue()

    try:
        # Wait for queue to be empty (with timeout)
        start_time = time.time()
        while not queue.upload_queue.empty():
            if time.time() - start_time > timeout:
                logger.warning(
                    f"⚠️ Timeout waiting for upload queue to empty after {timeout}s")
                return False
            time.sleep(0.5)

        # Small delay to ensure last upload is fully processed
        time.sleep(1.0)

        # Now sort the sheet
        from finance_core.google_sheets import sort_google_sheet_transactions
        expense_sorted, income_sorted = sort_google_sheet_transactions()

        logger.info(
            f"✅ Sheet sorted after uploads: {expense_sorted} expenses, {income_sorted} income")
        return True

    except Exception as e:
        logger.error(f"❌ Error sorting sheet after uploads: {e}")
        return False


async def sort_sheet_after_uploads_async(timeout: float = 60.0) -> bool:
    """
    Async version: Wait for the upload queue to empty, then sort the Google Sheet.

    This is designed to be called from async Discord bot code without blocking.

    Args:
        timeout: Maximum time to wait for queue to empty (in seconds)

    Returns:
        True if sort was successful, False otherwise
    """
    import asyncio

    queue = get_upload_queue()

    try:
        # Wait for queue to be empty (with timeout) - async sleep to not block
        # event loop
        start_time = time.time()
        while not queue.upload_queue.empty():
            if time.time() - start_time > timeout:
                logger.warning(
                    f"⚠️ Timeout waiting for upload queue to empty after {timeout}s")
                return False
            await asyncio.sleep(0.5)

        # Small delay to ensure last upload is fully processed
        await asyncio.sleep(1.0)

        # Now sort the sheet (run in executor to not block event loop)
        loop = asyncio.get_event_loop()
        from finance_core.google_sheets import sort_google_sheet_transactions
        expense_sorted, income_sorted = await loop.run_in_executor(
            None, sort_google_sheet_transactions
        )

        logger.info(
            f"✅ Sheet sorted after uploads: {expense_sorted} expenses, {income_sorted} income")
        return True

    except Exception as e:
        logger.error(f"❌ Error sorting sheet after uploads: {e}")
        return False
