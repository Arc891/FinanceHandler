# finance_core/google_sheets.py

import gspread
import logging
from typing import List, Dict, Any, Tuple, Optional
from google.oauth2.service_account import Credentials
from config.config_settings import GSHEET_NAME, GSHEET_TAB
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
            raise FileNotFoundError(
                f"Google credentials file not found: {credentials_path}")

    def _authorize(self):
        """Authorize and connect to Google Sheets"""
        if self.client is None:
            scope = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file(
                self.credentials_path, scopes=scope)
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
                logger.info(
                    f"✅ Opened worksheet: {GSHEET_NAME} - {GSHEET_TAB}")

            except gspread.SpreadsheetNotFound:
                raise Exception(
                    f"Spreadsheet '{GSHEET_NAME}' not found. Please check the name and permissions.")
            except gspread.WorksheetNotFound:
                raise Exception(
                    f"Worksheet '{GSHEET_TAB}' not found in '{GSHEET_NAME}'")
            except Exception as e:
                logger.error(f"❌ Unexpected error accessing sheet: {e}")
                raise
        return self.sheet

    def ensure_sheet_capacity(self, required_row: int,
                              buffer_rows: int = 50) -> bool:
        """
        Ensure the sheet has enough rows to accommodate the required row.
        Expands the sheet if necessary with a buffer for future transactions.

        Args:
            required_row: The row number that needs to be available
            buffer_rows: Additional rows to add beyond the required row for safety

        Returns:
            True if sheet was expanded, False if no expansion was needed
        """
        try:
            sheet = self._get_worksheet()
            current_row_count = sheet.row_count

            if required_row <= current_row_count:
                logger.debug(
                    f"✅ Sheet has sufficient capacity: {current_row_count} rows, need row {required_row}")
                return False

            # Calculate new row count with buffer
            new_row_count = required_row + buffer_rows

            logger.info(
                f"📏 Expanding sheet from {current_row_count} to {new_row_count} rows (need row {required_row} + {buffer_rows} buffer)")

            # Resize the worksheet
            sheet.resize(rows=new_row_count)

            logger.info(
                f"✅ Successfully expanded sheet to {new_row_count} rows")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to expand sheet: {e}")
            raise Exception(
                f"Could not expand sheet to accommodate row {required_row}: {e}")

    def refresh_worksheet(self):
        """Force re-fetch of the worksheet to get fresh metadata (row count, etc.)"""
        self.sheet = None
        return self._get_worksheet()

    def check_row_bounds(self, target_row: int, use_cache: bool = False) -> bool:
        """
        Check if a target row is within the current sheet bounds.

        Args:
            target_row: The row number to check
            use_cache: If True, use cached worksheet (avoids API call).
                       If False (default), forces a metadata refresh.

        Returns:
            True if the row is within bounds, False otherwise
        """
        try:
            sheet = self._get_worksheet() if use_cache else self.refresh_worksheet()
            return target_row <= sheet.row_count
        except Exception as e:
            logger.error(f"❌ Failed to check sheet bounds: {e}")
            return False

    def format_transaction_for_sheet(
            self, transaction: Dict[str, Any]) -> List[Any]:
        """
        Format a single transaction for Google Sheets export.

        Args:
            transaction: Transaction dict with category field added

        Returns:
            List of values: [date, amount, description, category]
            Note: amount is returned as float for proper Google Sheets formatting
        """
        # Extract date
        date_str = transaction.get("booking_date", "")

        # Extract and format amount
        amount_data = transaction.get("transaction_amount", {})
        amount_str = amount_data.get("amount", "0")
        try:
            amount = float(amount_str)
            # Check if transaction was manually switched from its original type
            if transaction.get("manually_switched", False):
                # If switched, use negative of the absolute amount to represent
                # the opposite flow
                amount_value = -abs(amount)
            else:
                # Normal case: use absolute amount
                amount_value = abs(amount)
        except ValueError:
            amount_value = 0.0

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
        description = " - ".join(
            description_parts) if description_parts else "Unknown Transaction"

        # Truncate description if too long (Google Sheets cell limit)
        if len(description) > 500:
            description = description[:497] + "..."

        # Get category (should have been added during categorization)
        category = transaction.get("category", "Uncategorized")

        return [date_str, amount_value, description, category]

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
                # +1 because we start from row 2
                end_row_exp = 1 + len(expense_values)
                range_exp = f"B2:E{end_row_exp + 1}"
                sheet.update(expense_values, range_exp)
                logger.info(
                    f"✅ Wrote {len(expense_values)} expenses to {range_exp}")

            # Write incomes to columns G-J (starting from row 2)
            if income_values:
                # +1 because we start from row 2
                end_row_inc = 1 + len(income_values)
                range_inc = f"G2:J{end_row_inc + 1}"
                sheet.update(income_values, range_inc)
                logger.info(
                    f"✅ Wrote {len(income_values)} incomes to {range_inc}")

            logger.info(
                f"🎉 Successfully exported {len(expense_values)} expenses and {len(income_values)} incomes to Google Sheets")
            return len(expense_values), len(income_values)

        except Exception as e:
            logger.error(f"❌ Error writing to Google Sheets: {str(e)}")
            raise

    def sort_transactions_by_date(
            self, sort_expenses: bool = True, sort_income: bool = True) -> Tuple[int, int]:
        """
        Sort expense and income transactions by date (column B for expenses, column G for income).
        Uses Python date parsing to ensure proper chronological order (not lexicographic).

        Args:
            sort_expenses: Whether to sort expense transactions (columns B-E)
            sort_income: Whether to sort income transactions (columns G-J)

        Returns:
            Tuple of (expense_rows_sorted, income_rows_sorted)
        """
        import re
        from datetime import datetime

        date_pattern = re.compile(
            r'^\d{1,2}-\d{1,2}-\d{4}$')  # DD-MM-YYYY format

        def parse_date(date_str: str) -> datetime:
            """Parse DD-MM-YYYY date string to datetime for proper sorting."""
            try:
                return datetime.strptime(date_str.strip(), "%d-%m-%Y")
            except (ValueError, AttributeError):
                return datetime(1970, 1, 1)  # Fallback for invalid dates

        def find_and_sort_data(
                values: List[List[Any]], start_offset: int = 1) -> Tuple[int, int, List[List[Any]]]:
            """
            Find rows with date data, sort them chronologically, return range and sorted data.
            Returns (first_row, last_row, sorted_data) where rows are 1-based sheet row numbers.
            """
            # Find rows that contain date data
            data_rows = []
            first_data_row = None
            last_data_row = None

            for i, row in enumerate(values):
                if row and len(row) > 0 and row[0]:
                    cell_value = str(row[0]).strip()
                    if date_pattern.match(cell_value):
                        actual_row = i + start_offset
                        if first_data_row is None:
                            first_data_row = actual_row
                        last_data_row = actual_row
                        # Pad row to 4 columns if needed
                        padded_row = row + \
                            [''] * (4 - len(row)) if len(row) < 4 else row[:4]
                        data_rows.append(padded_row)

            if not data_rows or len(data_rows) <= 1:
                return first_data_row, last_data_row, []

            # Sort by date (first column) chronologically
            sorted_data = sorted(data_rows,
                                 key=lambda r: parse_date(str(r[0])))

            return first_data_row, last_data_row, sorted_data

        try:
            sheet = self._get_worksheet()
            expense_sorted = 0
            income_sorted = 0

            if sort_expenses:
                # Get expense data (columns B-E)
                expense_values = sheet.get('B1:E500')
                if expense_values:
                    first_row, last_row, sorted_data = find_and_sort_data(
                        expense_values, start_offset=1)

                    if sorted_data and len(sorted_data) > 1:
                        sort_range = f"B{first_row}:E{last_row}"
                        logger.info(
                            f"📊 Sorting {len(sorted_data)} expenses in range {sort_range} chronologically...")

                        # Write sorted data back to sheet
                        # Use USER_ENTERED to preserve number/currency formatting
                        sheet.update(sorted_data, sort_range, value_input_option='USER_ENTERED')
                        expense_sorted = len(sorted_data)
                        logger.info(
                            f"✅ Sorted {expense_sorted} expense rows by date")
                    elif first_row == last_row:
                        logger.info(
                            "📊 Only one expense row found, no sorting needed")
                    else:
                        logger.info("📊 No expense data rows found to sort")

            if sort_income:
                # Get income data (columns G-J)
                income_values = sheet.get('G1:J500')
                if income_values:
                    first_row, last_row, sorted_data = find_and_sort_data(
                        income_values, start_offset=1)

                    if sorted_data and len(sorted_data) > 1:
                        sort_range = f"G{first_row}:J{last_row}"
                        logger.info(
                            f"📊 Sorting {len(sorted_data)} income in range {sort_range} chronologically...")

                        # Write sorted data back to sheet
                        # Use USER_ENTERED to preserve number/currency formatting
                        sheet.update(sorted_data, sort_range, value_input_option='USER_ENTERED')
                        income_sorted = len(sorted_data)
                        logger.info(
                            f"✅ Sorted {income_sorted} income rows by date")
                    elif first_row == last_row:
                        logger.info(
                            "📊 Only one income row found, no sorting needed")
                    else:
                        logger.info("📊 No income data rows found to sort")

            logger.info(
                f"🎉 Sort complete: {expense_sorted} expenses, {income_sorted} income rows")
            return expense_sorted, income_sorted

        except Exception as e:
            logger.error(f"❌ Error sorting transactions: {str(e)}")
            raise


def sort_google_sheet_transactions(
    credentials_path: Optional[str] = None,
    sort_expenses: bool = True,
    sort_income: bool = True
) -> Tuple[int, int]:
    """
    Convenience function to sort transactions in Google Sheets by date.

    Args:
        credentials_path: Path to Google service account credentials file
        sort_expenses: Whether to sort expense transactions
        sort_income: Whether to sort income transactions

    Returns:
        Tuple of (expense_rows_sorted, income_rows_sorted)
    """
    if credentials_path is None:
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

    exporter = GoogleSheetsExporter(credentials_path)
    return exporter.sort_transactions_by_date(sort_expenses, sort_income)


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
            from config.config_settings import GOOGLE_CREDENTIALS_PATH
            credentials_path = GOOGLE_CREDENTIALS_PATH
        except ImportError:
            # Fallback to default path
            base_dir = os.path.dirname(
                os.path.dirname(
                    os.path.abspath(__file__)))
            credentials_path = os.path.join(
                base_dir, "config", "google_service_account.json")

    # Check if Google Sheets is enabled
    try:
        from config.config_settings import GOOGLE_SHEETS_ENABLED
        if not GOOGLE_SHEETS_ENABLED:
            raise Exception(
                "Google Sheets integration is disabled in configuration")
    except ImportError:
        pass  # Assume enabled if config not available

    exporter = GoogleSheetsExporter(credentials_path)
    return exporter.write_transactions_to_sheet(
        income_transactions, expense_transactions)
