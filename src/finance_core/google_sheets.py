# finance_core/google_sheets.py

import gspread
import logging
from typing import List, Dict, Any, Tuple, Optional
from google.oauth2.service_account import Credentials
from config_settings import GSHEET_NAME, GSHEET_TAB
import os

logger = logging.getLogger(__name__)

class GoogleSheetsExporter:
    """Handles exporting categorized transactions to Google Sheets"""
    
    def __init__(self, credentials_path: str):
        """
        Initialize GoogleSheetsExporter with service account credentials.
        
        Args:
            credentials_path: Path to the Google service account JSON file
        """
        self.credentials_path = credentials_path
        self.client: Optional[gspread.Client] = None
        self.sheet = None
        
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Google credentials file not found: {credentials_path}")
    
    def _authorize(self):
        """Authorize and connect to Google Sheets"""
        if self.client is None:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file(self.credentials_path, scopes=scope)
            self.client = gspread.authorize(creds)
            logger.info("✅ Google Sheets authorization successful")
    
    def _get_worksheet(self):
        """Get the worksheet object"""
        if self.sheet is None:
            self._authorize()
            if self.client is None:
                raise Exception("Failed to authorize Google Sheets client")
            try:
                # First try to open the spreadsheet
                spreadsheet = self.client.open(GSHEET_NAME)
                logger.info(f"✅ Opened spreadsheet: {GSHEET_NAME}")
                
                # Then try to get the specific worksheet
                self.sheet = spreadsheet.worksheet(GSHEET_TAB)
                logger.info(f"✅ Opened worksheet: {GSHEET_NAME} - {GSHEET_TAB}")
            
            except gspread.SpreadsheetNotFound:
                raise Exception(f"Spreadsheet '{GSHEET_NAME}' not found. Please check the name and permissions.")
            except gspread.WorksheetNotFound:
                raise Exception(f"Worksheet '{GSHEET_TAB}' not found in '{GSHEET_NAME}'")
            except Exception as e:
                logger.error(f"❌ Unexpected error accessing sheet: {e}")
                raise
        return self.sheet
    
    def format_transaction_for_sheet(self, transaction: Dict[str, Any]) -> List[str]:
        """
        Format a single transaction for Google Sheets export.
        
        Args:
            transaction: Transaction dict with category field added
            
        Returns:
            List of values: [date, amount, description, category]
        """
        # Extract date
        date_str = transaction.get("booking_date", "")
        
        # Extract and format amount
        amount_data = transaction.get("transaction_amount", {})
        amount_str = amount_data.get("amount", "0")
        try:
            amount = float(amount_str)
            # Format as positive value with comma as decimal separator (European style)
            amount_formatted = f"{abs(amount):.2f}".replace('.', ',')
        except ValueError:
            amount_formatted = "0,00"
        
        # Extract description from multiple sources
        description_parts = []
        
        # Check for provided description first (highest priority)
        if user_desc := transaction.get("description"):
            description_parts.append(user_desc)
        else:
            # Fallback to auto-extracting from bank data
            # Add counterparty information
            debtor_name = transaction.get("debtor", {}).get("name", "")
            creditor_name = transaction.get("creditor", {}).get("name", "")
            counterparty = debtor_name or creditor_name
            if counterparty:
                description_parts.append(counterparty)
            
            # Add remittance information
            remittance = transaction.get("remittance_information", [])
            if remittance and remittance[0]:
                description_parts.append(remittance[0])
        
        # Combine description parts
        description = " - ".join(description_parts) if description_parts else "Unknown Transaction"
        
        # Truncate description if too long (Google Sheets cell limit)
        if len(description) > 500:
            description = description[:497] + "..."
        
        # Get category (should have been added during categorization)
        category = transaction.get("category", "Uncategorized")
        
        return [date_str, amount_formatted, description, category]
    
    def write_transactions_to_sheet(
        self, 
        income_transactions: List[Dict[str, Any]], 
        expense_transactions: List[Dict[str, Any]]
    ) -> Tuple[int, int]:
        """
        Write categorized income and expense transactions to Google Sheets.
        
        Args:
            income_transactions: List of categorized income transactions
            expense_transactions: List of categorized expense transactions
            
        Returns:
            Tuple of (expense_count, income_count)
        """
        try:
            sheet = self._get_worksheet()
            
            # Format transactions for Google Sheets
            expense_values = [
                self.format_transaction_for_sheet(tx) 
                for tx in expense_transactions
            ]
            
            income_values = [
                self.format_transaction_for_sheet(tx) 
                for tx in income_transactions
            ]
            
            # Clear existing data in both expense and income columns
            last_row = max(sheet.row_count, 100)  # Ensure we clear enough rows
            ranges_to_clear = [f"B2:E{last_row}", f"G2:J{last_row}"]
            sheet.batch_clear(ranges_to_clear)
            logger.info("✅ Cleared existing data from Google Sheet")
            
            # Write expenses to columns B-E (starting from row 2)
            if expense_values:
                end_row_exp = 1 + len(expense_values)  # +1 because we start from row 2
                range_exp = f"B2:E{end_row_exp + 1}"
                sheet.update(expense_values, range_exp)
                logger.info(f"✅ Wrote {len(expense_values)} expenses to {range_exp}")
            
            # Write incomes to columns G-J (starting from row 2)
            if income_values:
                end_row_inc = 1 + len(income_values)  # +1 because we start from row 2
                range_inc = f"G2:J{end_row_inc + 1}"
                sheet.update(income_values, range_inc)
                logger.info(f"✅ Wrote {len(income_values)} incomes to {range_inc}")
            
            logger.info(f"🎉 Successfully exported {len(expense_values)} expenses and {len(income_values)} incomes to Google Sheets")
            return len(expense_values), len(income_values)
            
        except Exception as e:
            logger.error(f"❌ Error writing to Google Sheets: {str(e)}")
            raise

def export_to_google_sheets(
    income_transactions: List[Dict[str, Any]], 
    expense_transactions: List[Dict[str, Any]],
    credentials_path: Optional[str] = None
) -> Tuple[int, int]:
    """
    Convenience function to export transactions to Google Sheets.
    
    Args:
        income_transactions: List of categorized income transactions
        expense_transactions: List of categorized expense transactions
        credentials_path: Path to Google service account credentials file
        
    Returns:
        Tuple of (expense_count, income_count)
    """
    if credentials_path is None:
        try:
            from config_settings import GOOGLE_CREDENTIALS_PATH
            credentials_path = GOOGLE_CREDENTIALS_PATH
        except ImportError:
            # Fallback to default path
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            credentials_path = os.path.join(base_dir, "config", "google_service_account.json")
    
    # Check if Google Sheets is enabled
    try:
        from config_settings import GOOGLE_SHEETS_ENABLED
        if not GOOGLE_SHEETS_ENABLED:
            raise Exception("Google Sheets integration is disabled in configuration")
    except ImportError:
        pass  # Assume enabled if config not available
    
    exporter = GoogleSheetsExporter(credentials_path)
    return exporter.write_transactions_to_sheet(income_transactions, expense_transactions)
