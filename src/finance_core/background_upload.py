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
        
        # Track row positions in sheet
        self.current_expense_row = 2  # Start at row 2 (row 1 is header)
        self.current_income_row = 2
        self.row_positions_file = "data/sheet_positions.json"
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 2.0  # 2 seconds between requests
        
        self._load_row_positions()
        
    def _load_row_positions(self):
        """Load the current row positions from file"""
        try:
            if os.path.exists(self.row_positions_file):
                with open(self.row_positions_file, 'r') as f:
                    data = json.load(f)
                    self.current_expense_row = data.get('expense_row', 2)
                    self.current_income_row = data.get('income_row', 2)
                    logger.info(f"📍 Loaded row positions: expenses={self.current_expense_row}, income={self.current_income_row}")
            else:
                # First time - need to detect current positions from sheet
                self._detect_current_positions()
        except Exception as e:
            logger.error(f"❌ Error loading row positions: {e}")
            self._detect_current_positions()
    
    def _save_row_positions(self):
        """Save current row positions to file"""
        try:
            os.makedirs(os.path.dirname(self.row_positions_file), exist_ok=True)
            data = {
                'expense_row': self.current_expense_row,
                'income_row': self.current_income_row,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.row_positions_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Error saving row positions: {e}")
    
    def _detect_current_positions(self):
        """Detect current last row positions in the Google Sheet"""
        try:
            if not self.exporter:
                self.exporter = GoogleSheetsExporter(self.credentials_path)
            
            sheet = self.exporter._get_worksheet()
            
            logger.info(f"🔍 Detecting row positions in Google Sheet...")
            
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
            
            logger.info(f"🔍 Detected row positions: expenses={self.current_expense_row}, income={self.current_income_row}")
            self._save_row_positions()
            
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
        self.upload_queue.put(upload)
        logger.debug(f"📝 Queued {transaction_type} transaction for upload (queue size: {self.upload_queue.qsize()})")
    
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
            if not self.exporter:
                self.exporter = GoogleSheetsExporter(self.credentials_path)
            
            sheet = self.exporter._get_worksheet()
            
            # Format transaction for sheet
            formatted_data = self.exporter.format_transaction_for_sheet(upload.transaction)
            
            # Determine target row and columns
            if upload.transaction_type == "expense":
                target_row = self.current_expense_row
                target_range = f"B{target_row}:E{target_row}"
                check_range = f"B{target_row}:E{target_row}"
            else:  # income
                target_row = self.current_income_row
                target_range = f"G{target_row}:J{target_row}"
                check_range = f"G{target_row}:J{target_row}"
            
            # SAFETY CHECK: Verify target row is empty before uploading
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
                            logger.info(f"✅ Corrected expense row from {self.current_expense_row - 1} to {target_row}")
                        else:
                            income_values = sheet.get('G:J')
                            corrected_row = self._find_last_data_row(income_values)
                            self.current_income_row = corrected_row
                            target_row = corrected_row
                            target_range = f"G{target_row}:J{target_row}"
                            logger.info(f"✅ Corrected income row from {self.current_income_row - 1} to {target_row}")
                        
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
            
            # Upload to sheet
            sheet.update([formatted_data], target_range)
            
            # Update row position after successful upload
            if upload.transaction_type == "expense":
                self.current_expense_row = target_row + 1
            else:
                self.current_income_row = target_row + 1
            
            # Save updated positions
            self._save_row_positions()
            
            logger.info(f"✅ Uploaded {upload.transaction_type} to {target_range}: {formatted_data[2][:50]}...")
            
        except Exception as e:
            logger.error(f"❌ Failed to upload transaction: {e}")
            # Could implement retry logic here if needed
            raise
    
    def reset_row_positions(self):
        """Force a complete reset and re-detection of row positions from the Google Sheet"""
        logger.warning(f"🔄 Forcing complete reset of row positions...")
        
        # Clear cached positions
        self.current_expense_row = 2
        self.current_income_row = 2
        
        # Force re-detection
        self._detect_current_positions()
        
        logger.info(f"✅ Row positions reset and re-detected: expenses={self.current_expense_row}, income={self.current_income_row}")

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
