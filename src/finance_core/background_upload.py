"""
Background Google Sheets upload queue with throttling.
Handles immediate transaction uploads with proper rate limiting.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading
import time
from queue import Queue, Empty
import json
import os

from finance_core.google_sheets import GoogleSheetsExporter

logger = logging.getLogger(__name__)

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
    
    def __init__(self, credentials_path: str):
        self.credentials_path = credentials_path
        self.upload_queue = Queue()
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.exporter: Optional[GoogleSheetsExporter] = None
        
        # Track row positions - will be loaded per user when needed
        self.current_expense_row = 2  # Default fallback
        self.current_income_row = 2
        self.current_user_id = None  # Track which user's positions we have loaded
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 2.0  # 2 seconds between requests
    
    def _load_row_positions(self, user_id: int):
        """Load the current row positions for a specific user"""
        from finance_core.session_management import get_sheet_positions
        
        try:
            positions = get_sheet_positions(user_id)
            self.current_expense_row = positions.get('expense_row', 2)
            self.current_income_row = positions.get('income_row', 2)
            self.current_user_id = user_id
            logger.info(f"📍 Loaded row positions for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")
            
            # If no positions saved yet, detect them
            if positions.get('last_updated') is None:
                self._detect_current_positions(user_id)
            else:
                # If cached positions are very high (>10), verify the sheet actually has that much data
                # This prevents using stale positions when the sheet was cleared
                if self.current_expense_row > 10 or self.current_income_row > 10:
                    logger.info(f"🔍 Cached positions seem high (exp:{self.current_expense_row}, inc:{self.current_income_row}), verifying with sheet...")
                    
                    # Quick check to see if sheet actually has data at those positions
                    if not self.exporter:
                        self.exporter = GoogleSheetsExporter(self.credentials_path)
                    sheet = self.exporter._get_worksheet()
                    
                    # Check if there's actually data near the cached positions
                    try:
                        check_range = f"B{max(1, self.current_expense_row-5)}:J{self.current_expense_row}"
                        check_data = sheet.get(check_range)
                        
                        # Count non-empty rows
                        data_rows = 0
                        if check_data:
                            for row in check_data:
                                if any(str(cell).strip() for cell in row if cell):
                                    data_rows += 1
                        
                        if data_rows < 3:  # If less than 3 rows of data found, sheet is likely empty
                            logger.warning(f"⚠️ Cached positions point to mostly empty area ({data_rows} data rows found)")
                            logger.warning(f"⚠️ Sheet may have been cleared - forcing fresh detection")
                            self._detect_current_positions(user_id)
                        else:
                            logger.info(f"✅ Sheet has {data_rows} data rows, cached positions seem valid")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not verify cached positions: {e}, forcing fresh detection")
                        self._detect_current_positions(user_id)
                        
        except Exception as e:
            logger.error(f"❌ Error loading row positions: {e}")
            self._detect_current_positions(user_id)
            self._detect_current_positions(user_id)
    
    def _save_row_positions(self, user_id: int):
        """Save current row positions for a specific user"""
        from finance_core.session_management import save_sheet_positions
        
        try:
            save_sheet_positions(user_id, self.current_expense_row, self.current_income_row)
            logger.debug(f"💾 Saved row positions for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")
        except Exception as e:
            logger.error(f"❌ Error saving row positions: {e}")
    
    def _detect_current_positions(self, user_id: int):
        """Detect current last row positions in the Google Sheet for a specific user"""
        try:
            if not self.exporter:
                self.exporter = GoogleSheetsExporter(self.credentials_path)
            
            sheet = self.exporter._get_worksheet()
            
            logger.info(f"🔍 Detecting row positions in Google Sheet for user {user_id}...")
            
            # Find last non-empty row in expense columns (B-E) - using a more robust method
            expense_values = sheet.get('B:E')
            logger.debug(f"🔍 Retrieved {len(expense_values) if expense_values else 0} rows from expense columns (B:E)")
            self.current_expense_row = self._find_last_data_row(expense_values)
            
            # Find last non-empty row in income columns (G-J)  
            income_values = sheet.get('G:J')
            logger.debug(f"🔍 Retrieved {len(income_values) if income_values else 0} rows from income columns (G:J)")
            self.current_income_row = self._find_last_data_row(income_values)
            
            # Ensure we start at least at row 2
            self.current_expense_row = max(self.current_expense_row, 2)
            self.current_income_row = max(self.current_income_row, 2)
            
            logger.info(f"🔍 Detected row positions for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")
            self._save_row_positions(user_id)
            
        except Exception as e:
            logger.error(f"❌ Error detecting row positions: {e}")
            # Fallback to safe defaults
            self.current_expense_row = 2
            self.current_income_row = 2
    
    def _find_last_data_row(self, values):
        """Find the last row that contains actual data (more robust method)"""
        if not values:
            logger.debug("🔍 No values found, returning row 1")
            return 1  # Start at row 2 (1 + 1)
        
        last_data_row = 0
        for i, row in enumerate(values):
            # Check if any cell in this row has non-empty, non-whitespace content
            has_data = False
            row_content = []
            for cell in row:
                cell_str = str(cell).strip() if cell else ""
                row_content.append(f"'{cell_str}'")
                if cell_str:
                    has_data = True
            
            # Debug log for each row being checked (only for first 20 rows to avoid spam)
            if i < 20:
                logger.debug(f"🔍 Row {i+1}: {row_content} - Has data: {has_data}")
            
            if has_data:
                last_data_row = i + 1  # Convert to 1-based row number
        
        # Return the next available row (last data row + 1)
        next_row = last_data_row + 1
        logger.info(f"🔍 Analysis complete: Last data row: {last_data_row}, next available row: {next_row}")
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
    
    def queue_transaction(self, transaction: Dict[str, Any], transaction_type: str, user_id: int):
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
        if 'cache_id' in transaction and not transaction.get('_is_replacement'):
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
            update_cached_transaction_row(user_id, transaction['cache_id'], reserved_row)
            
            logger.info(f"📍 Reserved row {reserved_row} for cached transaction {transaction['cache_id']} ({transaction_type})")
        
        self.upload_queue.put(upload)
        
        upload_type = "replacement" if transaction.get('_is_replacement') else "upload"
        cache_info = f" (cache_id: {transaction.get('cache_id', 'N/A')})"
        logger.debug(f"📝 Queued {transaction_type} transaction for {upload_type} (queue size: {self.upload_queue.qsize()}){cache_info}")
    
    def queue_cached_replacement(self, cache_id: str, new_transaction: Dict[str, Any], transaction_type: str, user_id: int):
        """Queue a cached transaction replacement"""
        replacement = CachedTransactionReplacement(
            cache_id=cache_id,
            new_transaction=new_transaction,
            transaction_type=transaction_type,
            user_id=user_id,
            timestamp=datetime.now()
        )
        
        # Add the cache_id and replacement flag to the transaction
        # Preserve any existing fields like _reserved_row
        new_transaction_with_cache = {**new_transaction, "cache_id": cache_id, "_is_replacement": True}
        self.queue_transaction(new_transaction_with_cache, transaction_type, user_id)
        logger.info(f"🔄 Queued replacement for cached transaction {cache_id} (reserved_row: {new_transaction.get('_reserved_row', 'N/A')})")

    def _rate_limit(self):
        """Ensure we don't exceed rate limits"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            logger.debug(f"⏱️ Rate limiting: sleeping {sleep_time:.1f}s")
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
                
                # Upload the transaction
                self._upload_single_transaction(upload)
                
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
    
    def _upload_single_transaction(self, upload: TransactionUpload):
        """Upload a single transaction to Google Sheets"""
        try:
            # Ensure we have positions loaded for this user
            if self.current_user_id != upload.user_id:
                self._load_row_positions(upload.user_id)
            
            if not self.exporter:
                self.exporter = GoogleSheetsExporter(self.credentials_path)
            
            sheet = self.exporter._get_worksheet()
            
            # Format transaction for sheet
            formatted_data = self.exporter.format_transaction_for_sheet(upload.transaction)
            
            # For cached transactions, check if row was already reserved during queuing
            target_row = None
            use_reserved_row = False
            
            if 'cache_id' in upload.transaction:
                # Check if this is a replacement with a pre-stored reserved row
                if upload.transaction.get('_is_replacement') and upload.transaction.get('_reserved_row'):
                    target_row = upload.transaction['_reserved_row']
                    use_reserved_row = True
                    logger.info(f"🔄 Using pre-stored reserved row {target_row} for replacement of cached transaction {upload.transaction['cache_id']}")
                else:
                    # For non-replacements, look up the cached transaction to get the reserved row
                    from finance_core.session_management import get_cached_transactions
                    cached_transactions = get_cached_transactions(upload.user_id)
                    
                    for cached_tx in cached_transactions:
                        if cached_tx["cache_id"] == upload.transaction['cache_id']:
                            logger.debug(f"🔍 Found cached transaction {upload.transaction['cache_id']} for user {upload.user_id}")
                            reserved_row = cached_tx.get("sheet_row")
                            if reserved_row:
                                target_row = reserved_row
                                use_reserved_row = True
                                logger.info(f"🎯 Using pre-reserved row {target_row} for cached transaction {upload.transaction['cache_id']}")
                                break
            
            # If no reserved row, use current positions (only for non-replacements)
            if not target_row:
                if upload.transaction.get('_is_replacement'):
                    logger.error(f"🚨 CRITICAL: Replacement transaction {upload.transaction.get('cache_id')} has no reserved row!")
                    logger.error(f"🚨 Debug info: {upload.transaction}")
                    return  # Abort replacement to prevent data corruption
                    
                if upload.transaction_type == "expense":
                    target_row = self.current_expense_row
                else:  # income
                    target_row = self.current_income_row
                logger.info(f"📍 Using current row {target_row} for {upload.transaction_type} transaction")
            
            # Determine target range based on transaction type
            if upload.transaction_type == "expense":
                target_range = f"B{target_row}:E{target_row}"
                check_range = f"B{target_row}:E{target_row}"
            else:  # income
                target_range = f"G{target_row}:J{target_row}"
                check_range = f"G{target_row}:J{target_row}"
            
            # SAFETY CHECK: Verify target row is empty before uploading
            # Skip safety check for replacements and pre-reserved rows (they should be safe by design)
            if not use_reserved_row and not upload.transaction.get('_is_replacement'):
                try:
                    existing_data = sheet.get(check_range)
                    if existing_data and existing_data[0]:
                        # Check if any cell has content
                        has_content = any(str(cell).strip() for cell in existing_data[0] if cell)
                        if has_content:
                            logger.error(f"🚨 CRITICAL: Target row {target_row} already contains data: {existing_data[0]}")
                            logger.error(f"🚨 This would overwrite existing data! Recalculating row position.")
                            
                            # Re-detect the actual next empty row from scratch
                            logger.info(f"🔄 Re-detecting row positions to find safe upload location...")
                            if upload.transaction_type == "expense":
                                expense_values = sheet.get('B:E')
                                corrected_row = self._find_last_data_row(expense_values)
                                self.current_expense_row = corrected_row
                                target_row = corrected_row
                                target_range = f"B{target_row}:E{target_row}"
                                logger.info(f"✅ Corrected expense row to {target_row}")
                            else:
                                income_values = sheet.get('G:J')
                                corrected_row = self._find_last_data_row(income_values)
                                self.current_income_row = corrected_row
                                target_row = corrected_row
                                target_range = f"G{target_row}:J{target_row}"
                                logger.info(f"✅ Corrected income row to {target_row}")
                            
                            # Double-check the corrected row is actually empty
                            check_range = target_range
                            double_check = sheet.get(check_range)
                            if double_check and double_check[0]:
                                double_check_content = any(str(cell).strip() for cell in double_check[0] if cell)
                                if double_check_content:
                                    logger.error(f"🚨 CRITICAL ERROR: Even corrected row {target_row} has data: {double_check[0]}")
                                    logger.error(f"🚨 Cannot safely upload transaction. Skipping to prevent data loss.")
                                    return  # Abort upload to prevent overwriting
                            
                            logger.info(f"✅ Double-checked: Row {target_row} is safe for upload")
                except Exception as e:
                    logger.warning(f"⚠️ Could not verify target row emptiness: {e}")
                    logger.warning(f"⚠️ Proceeding with upload but this may overwrite data!")
            else:
                if upload.transaction.get('_is_replacement'):
                    logger.info(f"🔄 Replacement transaction - skipping safety check for row {target_row}")
                else:
                    logger.info(f"🎯 Using pre-reserved row {target_row} - skipping safety check")
            
            # Upload to sheet
            sheet.update([formatted_data], target_range)
            
            # Handle cached transaction logic
            if 'cache_id' in upload.transaction:
                if upload.transaction.get('_is_replacement'):
                    # This is a replacement - try to remove the cached transaction from session
                    # (it might already be removed by the UI, which is fine)
                    try:
                        from finance_core.session_management import remove_cached_transaction
                        remove_cached_transaction(upload.user_id, upload.transaction['cache_id'])
                        logger.info(f"🔄 Replaced cached dummy and removed {upload.transaction['cache_id']} from cache")
                    except Exception as e:
                        logger.debug(f"ℹ️ Cached transaction {upload.transaction['cache_id']} already removed from session: {e}")
                elif not use_reserved_row:
                    # This is a new dummy cache - store the row for future replacement
                    from finance_core.session_management import update_cached_transaction_row
                    update_cached_transaction_row(upload.user_id, upload.transaction['cache_id'], target_row)
                    logger.info(f"📍 Stored sheet row {target_row} for cached transaction {upload.transaction['cache_id']}")
            
            # Update row position after successful upload (only for non-reserved rows and non-replacements)
            if not use_reserved_row and not upload.transaction.get('_is_replacement'):
                if upload.transaction_type == "expense":
                    self.current_expense_row = target_row + 1
                else:
                    self.current_income_row = target_row + 1
                
                # Save updated positions
                self._save_row_positions(upload.user_id)
                logger.debug(f"📍 Updated current positions: expense={self.current_expense_row}, income={self.current_income_row}")
            
            logger.info(f"✅ Uploaded {upload.transaction_type} to {target_range}: {formatted_data[2][:50]}...")
            
        except Exception as e:
            logger.error(f"❌ Failed to upload transaction: {e}")
            # Could implement retry logic here if needed
            raise
    
    def reset_row_positions(self, user_id: int):
        """Force a complete reset and re-detection of row positions from the Google Sheet"""
        logger.warning(f"🔄 Forcing complete reset of row positions for user {user_id}...")
        
        # Clear cached positions
        self.current_expense_row = 2
        self.current_income_row = 2
        self.current_user_id = None
        
        # Force re-detection
        self._detect_current_positions(user_id)
        
        logger.info(f"✅ Row positions reset and re-detected for user {user_id}: expenses={self.current_expense_row}, income={self.current_income_row}")

# Global instance
_upload_queue: Optional[GoogleSheetsUploadQueue] = None

def get_upload_queue() -> GoogleSheetsUploadQueue:
    """Get the global upload queue instance"""
    global _upload_queue
    if _upload_queue is None:
        try:
            from config_settings import GOOGLE_CREDENTIALS_PATH
            credentials_path = GOOGLE_CREDENTIALS_PATH
        except ImportError:
            # Fallback to default path
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            credentials_path = os.path.join(base_dir, "config", "google_service_account.json")
        
        _upload_queue = GoogleSheetsUploadQueue(credentials_path)
    return _upload_queue

def start_upload_queue():
    """Start the global upload queue"""
    queue = get_upload_queue()
    queue.start()

def stop_upload_queue():
    """Stop the global upload queue"""
    global _upload_queue
    if _upload_queue:
        _upload_queue.stop()

def queue_transaction_upload(transaction: Dict[str, Any], transaction_type: str, user_id: int):
    """Queue a transaction for background upload to Google Sheets"""
    queue = get_upload_queue()
    queue.queue_transaction(transaction, transaction_type, user_id)

def queue_cached_replacement(cache_id: str, new_transaction: Dict[str, Any], transaction_type: str, user_id: int):
    """Queue a cached transaction replacement"""
    queue = get_upload_queue()
    queue.queue_cached_replacement(cache_id, new_transaction, transaction_type, user_id)
