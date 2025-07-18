import enum
import json
import logging
import os
import re
import sys
import uuid
import gspread
import requests
import jwt as pyjwt

from constants import (
  ExpenseCategory, IncomeCategory,
  CATEGORIZATION_RULES_EXPENSE, CATEGORIZATION_RULES_INCOME,
  GSHEET_NAME, GSHEET_TAB,
)

from src.finance_core.csv_helper import load_transactions_from_csv, normalize_csv_data

from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timezone, timedelta
from pprint import pprint
from urllib.parse import urlparse, parse_qs
from google.oauth2.service_account import Credentials

BASEDIR = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
  level=logging.WARNING,
  format="%(asctime)s [%(levelname)s] %(message)s",
  handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

GOOGLE_CRED_FILE = os.path.join(BASEDIR, "config", "google_service_account.json")
if not os.path.exists(GOOGLE_CRED_FILE):
  logger.error(f"Cannot find {GOOGLE_CRED_FILE}. Download it from GCP.")
  sys.exit(1)



def prompt_icon(prompt_type: str):
   return "💵" if prompt_type == "Income" else "💸" 

def prompt(prompt_type: str):
   return f"{prompt_icon(prompt_type)}{prompt_type}{'' if prompt_type == 'Expense' else ' '}"

def auto_match_category(
  raw_cat: str,
  CategoryEnum: type[IncomeCategory] | type[ExpenseCategory],
) -> Optional[str]:
  """
  Attempt to auto‐match `raw_cat` against categories in `CategoryEnum`.
  Returns the matched category value or None if no match.
  """
  if not raw_cat:
    print("  [!] Category cannot be empty. Please try again.")
    return None

  # 1) Exact match
  exact_match = full_match_category(raw_cat, CategoryEnum)
  if exact_match:
    return exact_match

  # 2) Shorthand match
  shorthand_match = shorthand_match_category(raw_cat, CategoryEnum)
  if shorthand_match:
    return shorthand_match

  # 3) Substring match
  substring_match = substring_match_category(raw_cat, CategoryEnum)
  if substring_match and substring_match != 'None':
    return substring_match
  elif substring_match == 'None':
    return None
  
  # 4) No match at all
  print(f"  [!] No match found for '{raw_cat}' in {CategoryEnum.__name__}.")
  print(f"  [!] Available categories: {[m.value for m in CategoryEnum]}")

  return None

def full_match_category(
  raw_cat: str,
  CategoryEnum: type[IncomeCategory] | type[ExpenseCategory]
) -> (str | None):
  """
  Check if `raw_cat` matches any category in `CategoryEnum` exactly.
  Returns the matched category value or None if no match.
  """
  for member in CategoryEnum:
    if raw_cat.lower() == member.value.lower():
      return member.value
  return None

def shorthand_match_category(
  raw_cat: str,
  CategoryEnum: type[IncomeCategory] | type[ExpenseCategory]
) -> (str | None):
  """
  Check if `raw_cat` matches any shorthand pattern in `CategoryEnum`.
  Returns the matched category value or None if no match.
  """
  for member in CategoryEnum:
    if hasattr(member, "pattern") and re.search(member.pattern, raw_cat, re.IGNORECASE):
      return member.value
  return None

def substring_match_category(
  raw_cat: str,
  CategoryEnum: type[IncomeCategory] | type[ExpenseCategory]
) -> (str | None):
  """
  Check if `raw_cat` is a substring of any category in `CategoryEnum`.
  Returns the matched category value or None if no match.
  """
  matches = [
    member.value for member in CategoryEnum
    if re.search(re.escape(raw_cat), member.value, re.IGNORECASE)
  ]
  if len(matches) == 1:
    return matches[0]
  elif len(matches) > 1:
    print(f"Ambiguous match for '{raw_cat}'. Matches: {matches}")
    return 'None'
  return None

def categorize_transaction(
  tx: Dict[str, Any],
  is_expense: bool
) -> Tuple[str, str, bool]:
  """
  Attempt to auto‐categorize the transaction `tx` as either expense or income,
  based on is_expense. Returns (description, category, changed_type).
  
  - If is_expense=True, use expense rules and expense category list.
  - If is_expense=False, use income rules and income category list.
  """

  # Pick the correct rule set and category/shorthand lists
  rules = CATEGORIZATION_RULES_EXPENSE if is_expense else CATEGORIZATION_RULES_INCOME
  CategoryEnum = ExpenseCategory if is_expense else IncomeCategory
  prompt_type  = "Expense" if is_expense else "Income"
  changed_type = False

  # Extract and uppercase names for matching
  debtor        = tx.get("debtor") or {}
  creditor      = tx.get("creditor") or {}
  debtor_name   = debtor.get("name") or ""
  creditor_name = creditor.get("name") or ""
  rem_list      = tx.get("remittance_information") or []
  rem           = rem_list[0] if rem_list else ""
  name_fields   = f"{rem} {creditor_name}{debtor_name}" or "Unknown" # f"{debtor_name}" or f"{creditor_name}" or 
  amt           = (tx.get("transaction_amount") or {}).get("amount") or ""
  curr          = (tx.get("transaction_amount") or {}).get("currency") or ""

  # ─────────────────────────────────────────────────────────────────────────────
  # AUTO‐CATEGORIZE VIA rules (regex keys)
  # ─────────────────────────────────────────────────────────────────────────────
  for pattern, (desc_tmpl, cat) in rules.items():
    if re.search(pattern, name_fields, re.IGNORECASE):
      match = re.search(pattern, name_fields, re.IGNORECASE)
      if match and match.groups():
         company = match.group(2).title() if len(match.groups()) > 1 else match.groups()[0].title()
      else:
        company = match.group(0).title() if match else ""
      default_desc = desc_tmpl.format(c=company)
      print(f"✅ Matched {prompt(prompt_type)} of {amt:>8} to {default_desc} - {cat.value}")
      return default_desc, cat, changed_type

  # ─────────────────────────────────────────────────────────────────────────────
  # NO AUTOMATCH → PROMPT THE USER
  # ─────────────────────────────────────────────────────────────────────────────
  print(f"\n🔍 Could not auto-categorize this {prompt_type}.")
  date_str = tx.get("booking_date") or tx.get("value_date") or ""
  print(f"  • Date: {date_str}")
  print(f"  • Amount: {amt} {curr}")
  bank_code = (tx.get("bank_transaction_code") or {}).get("description") or ""
  print(f"  • Bank code desc: {bank_code}")
  print(f"  • Debtor name: {debtor_name}")
  print(f"  • Creditor name: {creditor_name}")
  print(f"  • Remittance info: {rem}")

  # If initially income, ask if the user wants to convert to expense
  if not is_expense:
    try:
      abs_amt = abs(float(amt))
    except ValueError:
      abs_amt = 0.0
    amt_display = f"{abs_amt:.2f}"
    ans = input(
      f"🔄 This is an INCOME of {amt_display} EUR by {(tx.get('creditor', {}) or {}).get('name', 'Unknown')}.\n"
      f"Type 'c' to treat it as an expense, "
      f"or press Enter to keep as income: "
    ).strip().lower()
    if ans == "c":
      is_expense = True
      CategoryEnum = ExpenseCategory
      prompt_type = "Expense"
      changed_type = True
  
  print(f"🔍 Could not auto-categorize this {prompt_type}. Please provide details:")
  
  # Ask user for a short description
  user_desc = input("  → Enter a short description: ").strip()
  if not user_desc:
    print(f"  [!] No description provided. Using: {name_fields}, category will be set to '{CategoryEnum.DEFAULT}'.")
    return name_fields, CategoryEnum.DEFAULT, changed_type

  # Now ask for category, validated against category_list + shorthand
  valid_category = None
  while valid_category is None:
    valid_category = auto_match_category(
      input(f"  → Enter {prompt_type} category (or partial): ").strip(),
      CategoryEnum,
    )
       

  print(f"  → Category set to: {valid_category}")
  return user_desc, valid_category, changed_type


def process_transactions(
  transactions: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
  """
  Splits `transactions` into expenses and incomes.
  Each transaction:
    1) Determine initial is_expense flag.
    2) If initially income (is_expense=False), prompt for conversion _before_ categorization.
    3) Call categorize_transaction(tx, is_expense) → (desc, cat).
    4) Store amt as positive float in both lists.
  Returns:
    - expenses: List of {date, amount, description, category}
    - incomes:  List of {date, amount, description, category}
  """

  expenses = []
  incomes  = []

  for tx in transactions:
    # 1) Extract core fields
    date_str = tx.get("booking_date") or tx.get("value_date") or ""
    amt_str  = (tx.get("transaction_amount") or {}).get("amount") or "0"
    try:
      amt = float(amt_str)
    except ValueError:
      amt = 0.0

    indicator = (tx.get("credit_debit_indicator") or "").upper()

    # 2) Determine initial type
    if indicator.startswith("DBIT") or indicator.startswith("DEBIT"):
      is_expense = True
    elif indicator.startswith("CRDT") or indicator.startswith("CRED"):
      is_expense = False
    else:
      is_expense = (amt < 0)

    # 4) Categorize with the final is_expense
    description, category, changed_type = categorize_transaction(tx, is_expense)
    is_expense = not is_expense if changed_type else is_expense

    # 5) Always write the amount as a positive float string
    amt_to_write = f"{'-' if changed_type else ''}{abs(amt):.2f}".replace('.', ',')

    row = {
      "date":        date_str,
      "amount":      amt_to_write,
      "description": description,
      "category":    category
    }

    if is_expense:
      expenses.append(row)
    else:
      incomes.append(row)

  return expenses, incomes


def write_to_sheet(transactions: List[Dict[str, Any]]) -> Tuple[int, int]:
  """
  Writes all expenses and incomes in two batch calls:
    1) B2:E{last_expense_row} for expenses
    2) G2:J{last_income_row} for incomes

  This avoids one-at-a-time update_cell calls and prevents 429 quota errors.
  """

  # 1) Authorize & open the worksheet
  scope = ["https://spreadsheets.google.com/feeds",
       "https://www.googleapis.com/auth/drive"]
  creds = Credentials.from_service_account_file(GOOGLE_CRED_FILE, scopes=scope)
  client = gspread.authorize(creds)
  sheet  = client.open(GSHEET_NAME).worksheet(GSHEET_TAB)

  # 2) Process transactions into two lists of rows (as lists of values)
  expenses, incomes = process_transactions(transactions)

  # Build a list of lists for expenses, where each sub-list is [date, amount, desc, category]
  expense_values = [
    [row["date"], row["amount"], row["description"], row["category"]]
    for row in expenses
  ]

  # Build a list of lists for incomes similarly
  income_values = [
    [row["date"], row["amount"], row["description"], row["category"]]
    for row in incomes
  ]

  # 3) Clear existing data (columns B–E and G–J from row 2 downward)
  last_row = max(sheet.row_count, 2)
  sheet.batch_clear([f"B2:E{last_row}", f"G2:J{last_row}"])
  
  # 4) Batch‐write expenses to B2:E{n+1}
  if expense_values:
    end_row_exp = 2 + len(expense_values) - 1  # last row index for expenses
    range_exp = f"B2:E{end_row_exp + 1}"     # e.g. "B2:E10"
    sheet.update(expense_values, range_exp) # type: ignore

  # 5) Batch‐write incomes to G2:J{m+1}
  if income_values:
    end_row_inc = 2 + len(income_values) - 1   # last row index for incomes
    range_inc = f"G2:J{end_row_inc + 1}"     # e.g. "G2:J8"
    sheet.update(income_values, range_inc) # type: ignore

  return len(expense_values), len(income_values)


def csv_extraction(csv_path: str):
  normalize_csv_data(csv_path)
  transactions = load_transactions_from_csv(csv_path)

  expense_count, income_count = write_to_sheet(transactions)
  print(f"✅ Wrote {expense_count} expenses and {income_count} incomes to '{GSHEET_NAME}'.")
  return 

def eb_extraction():
  """
  Extracts transactions from EnableBanking API and writes them to Google Sheets.
  This function initializes the EnableBanking client, fetches transactions,
  and prints the number of transactions extracted.
  """
  import enablebanking
  eb_client = enablebanking.enablebanking_extractor()
  transactions = eb_client.enablebanking_extraction()
  print(f"Extracted {len(transactions)} transactions from EnableBanking API.")
  return transactions

def check_csv_file(csv_path: str) -> bool:
  """
  Checks if the provided CSV file exists and is valid.
  Returns True if valid, False otherwise.
  """
  if not csv_path.endswith('.csv'):
    print("Error: The provided file is not a CSV file.")
    return False
  if not os.path.exists(csv_path):
    print(f"Error: CSV file '{csv_path}' does not exist.")
    return False
  return True


def main():
  """
  Main entry point for the script.
  - Loads transactions from CSV.
  - Processes and categorizes them.
  - Writes results to Google Sheets.
  """

  if len(sys.argv) < 2:
    print("Usage: python asnexport.py <csv_file_path>")
    sys.exit(1)
  
  csv_path = sys.argv[1]

  if not check_csv_file(csv_path):
    sys.exit(1)

  print("Starting CSV extraction and categorization...")
  csv_extraction(csv_path)
  print("Execution completed successfully.")
  return 

if __name__ == "__main__":
  main()