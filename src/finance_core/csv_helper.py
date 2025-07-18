import csv
from typing import Dict, List, Any
from config.spaarpot_uuid_map import SPAARPOT_UUID_MAP

# ─────────────────────────────────────────────────────────────────────────────
# Helper: Load transactions from a fixed‐column CSV export
# ─────────────────────────────────────────────────────────────────────────────
def load_transactions_from_csv(csv_path: str) -> List[Dict[str, Any]]:
  """
  Reads a CSV file (ASN export) and returns a list of transaction-dicts
  matching the shape expected by our categorization logic.

  Example:
  24-04-2025,NL24ASNB8844501082,NL72RABO0363944990,Anamata B.V.,,,,EUR,314.10,EUR,3637.65,24-04-2025,24-04-2025,8809,OVS,
  0         , 1                , 2                , 3       ,4,5,6, 7 , 8    , 9 , 10    , 11       , 12       , 13 , 14,
  979142,,'5-3215930-01-07-NL72RABO0363944990-Anamata B.V.-SALARISBETALING PERIODE 4',9,'Salaris'
  15  ,16, 17                                                                       ,18, 19           

  We assume each row has at least 18 columns (0-17), as in your example:
    0: booking_date (e.g. '24-04-2025')
    1: account_iban (ignored)
    2: counterparty_iban (ignored)
    3: counterparty_name (e.g. 'DUO Hoofdrekening' or 'Picnic' or 'Jumbo …')
    4-6: (ignored)
    7: (ignored)
    8: (ignored)
    9: transaction_currency (e.g. 'EUR')
   10: transaction_amount (string, e.g. '-80.68' or '314.00')
   11,12: (ignored)
   13: bank_transaction_code (e.g. '8809')
   14: sub_code (e.g. 'OVS')
   15: (ignored)
   16: (ignored)
   17: remittance_information (long string)

  For each row, we build a dict:
    - booking_date
    - transaction_amount: { amount: str, currency: str }
    - credit_debit_indicator: 'DBIT' if amount<0 else 'CRDT'
    - bank_transaction_code: { description: "<code> <sub_code>" }
    - debtor:   { name: counterparty_name } if expense, else {}
    - creditor: { name: counterparty_name } if income,  else {}
    - remittance_information: [ remittance ] or []

  Any rows with missing/empty booking_date are skipped.
  """

  normalize_csv_data(csv_path)

  txs: List[Dict[str, Any]] = []
  with open(csv_path, newline='', encoding='utf-8') as csvfile:
    reader = csv.reader(csvfile)
    for row in reader:
      # Skip empty lines or malformed rows
      if not row or len(row) < 18 or not row[0].strip():
        continue

      # 1) Extract fields by index
      booking_date = row[0].strip()
      counterparty_name = row[3].strip() if len(row) > 3 else ""
      currency = row[9].strip() if len(row) > 9 else ""
      amt_str = row[10].strip() if len(row) > 10 else "0"
      # Normalize decimal comma (if any) to dot
      amt_str = amt_str.replace(',', '.')  
      try:
        amt = float(amt_str)
      except ValueError:
        amt = 0.0

      code  = row[13].strip() if len(row) > 13 else ""
      sub_code = row[14].strip() if len(row) > 14 else ""
      bank_desc = f"{code} {sub_code}".strip()

      rem = row[17].strip() if len(row) > 17 else ""
      rem_list = [rem] if rem else []

      # 2) Determine credit/debit and set debtor/creditor names
      if amt < 0:
        credit_debit = "DBIT"
        debtor_name   = counterparty_name
        creditor_name = ""
      else:
        credit_debit = "CRDT"
        creditor_name = counterparty_name
        debtor_name   = ""

      tx = {
        "booking_date": booking_date,
        "transaction_amount": {
          "amount": f"{amt:.2f}",
          "currency": currency
        },
        "credit_debit_indicator": credit_debit,
        "bank_transaction_code": {
          "description": bank_desc
        },
        "debtor":   {"name": debtor_name},
        "creditor": {"name": creditor_name},
        "remittance_information": rem_list
      }
      txs.append(tx)

  return txs

# ─────────────────────────────────────────────────────────────────────────────
# Change some csv data to help with information extraction
# ─────────────────────────────────────────────────────────────────────────────
def normalize_csv_data(csv_path: str) -> None:
  """
  Reads a CSV file and normalizes specific fields to help with information extraction.
  This is a placeholder function; actual normalization logic should be implemented as needed.
  """

  with open(csv_path, newline='', encoding='utf-8') as csvfile:
    reader = csv.reader(csvfile)
    rows = [row for row in reader]

  for row in rows:
    for uuid in SPAARPOT_UUID_MAP.keys():
      if f"Referentie: {uuid}" in row[17]:
        # Row contains a UUID reference, change it to the mapped name
        name = SPAARPOT_UUID_MAP[uuid]
        print(f"Changing row {row} with {uuid} to {name}")
        row[17] = row[17].replace(f"Referentie: {uuid}", f"- {name}")
        print(f"Updated row: {row}")
        break
         
    if str(row).find("verzekeri ") != -1:
      print(f"Changing row {row} with 'verzekeri' to 'verzekering'")
      row[17] = row[17].replace("verzekeri", "verzekering")
  
  # Write the modified rows back to the CSV file
  with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerows(rows)
  
  print(f"CSV data normalized and saved to {csv_path}")