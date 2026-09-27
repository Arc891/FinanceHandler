# config_settings.py - Discord Bot Configuration Template
# Copy this file to config_settings.py and fill in your values
# All configuration is consolidated here - no .env file needed

import os
from typing import List
import logging

# ─────────────────────────────────────────────────────────────────────────────
# DISCORD BOT CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Discord Bot Token (get from Discord Developer Portal)
DISCORD_TOKEN = "your_discord_token_here"

# ─────────────────────────────────────────────────────────────────────────────
# DAILY REMINDER CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Daily reminder time in 24-hour format (HH:MM)
DAILY_REMINDER_TIME = "09:00"

# Discord Channel ID for daily reminders (right-click channel > Copy ID)
REMINDER_CHANNEL_ID = 0  # Replace with your channel ID

# Discord user IDs to mention in reminders
MENTION_USER_IDS: List[int] = [
    # Add Discord user IDs to mention in reminders
    # Example: 123456789012345678
]

# CSV Download Link for daily reminders (where users can download their transaction CSV)
# Set to None or empty string to disable the link in reminders
# Example: "https://bankname.com/export" or "https://yourdomain.com/csv"
CSV_DOWNLOAD_LINK = ""

# Timezone for reminder scheduling (uses system TZ environment variable,
# defaults to UTC)
TIMEZONE = os.environ.get('TZ', 'UTC')

# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE SHEETS CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Enable/disable Google Sheets integration
GOOGLE_SHEETS_ENABLED = True

# Multi-month upload (docs/plans/MULTI_MONTH_UPLOAD_PLAN.md 4.10)
# The bot runs on the user's own Google account via an OAuth token made once
# with scripts/google_login.py. The inspection scripts read with the service
# account key instead, passed as --credentials.
GOOGLE_OAUTH_CLIENT_PATH = "data/google/oauth_client.json"
GOOGLE_OAUTH_TOKEN_PATH = "data/google/authorized_user.json"
GSHEET_NAME_PATTERN = "Maandelijks Budget {label}"
GSHEET_TEMPLATE_ID = "1OSi4W3B3PrfCTQyxt3OreLmqSs4nXY82Wlg1_eohTs8"
GSHEET_FOLDER_ID = "1QoYs19vu04_DFIszlfWOJP7BoQLEtfaG"
GSHEET_AUTO_CREATE = True
GSHEET_CREATE_NONADJACENT = False               # only the month after the newest indexed one is created
GSHEET_DATA_START_ROW = 5                       # first data row of both blocks, below the headers
SHEET_INDEX_PATH = "data/sheet_index.json"      # AUTHORITATIVE; back it up
UPLOAD_LEDGER_PATH = "data/upload_ledger.json"
PERIOD_STATE_PATH = "data/period_state.json"
RUNS_DIR = "data/runs"

# Financial months (plan 4.3). A month starts on the first DUO or Anamata
# salary income of a new cycle; the constants come from measured 2026 spans.
PERIOD_BOUNDARY_MARKERS = [r"\bDUO\b", r"Anamata"]   # case-sensitive, counterparty or remittance
PERIOD_BOUNDARY_MIN_AMOUNT = 250.0              # below the smallest DUO payment
PERIOD_MIN_DAYS = 20                            # boundary-to-boundary is 27-32 days
PERIOD_MAX_DAYS = 35                            # marker-less rows past this abort the upload
PERIOD_STEP_DAYS = 29                           # fallback only, beyond the known history
PERIOD_LABEL_SPLIT_DAY = 15                     # boundary on day 15+ names the next month

# ─────────────────────────────────────────────────────────────────────────────
# FILE STORAGE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# File Upload Configuration
UPLOAD_DIR = "data/uploads"

# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATION CONFIGURATION (Session 1+)
# ─────────────────────────────────────────────────────────────────────────────

# Bank Scraping Configuration
BANK_SCRAPER_ENABLED = True
BANK_SESSION_FILE = "data/bank_session.json"
BANK_DOWNLOAD_DIR = "data/bank_downloads"

# ASN Bank Configuration
ASN_LOGIN_URL = "https://www.asnbank.nl/inloggen"
ASN_TRANSACTIONS_URL = "https://www.asnbank.nl/online/web/onlinebankieren/"
ASN_QR_TIMEOUT_SECONDS = 300  # 5 minutes for QR scan

# AI Categorization (Session 2 - will be configured later)
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')
AI_CONFIDENCE_THRESHOLD = 0.75  # below this an AI result is written flagged; set by the evaluation step
AI_PER_TX_FALLBACK_LIMIT = 10   # per-row AI calls per period when a batch chunk fails
AI_MAX_PARALLEL_CHUNKS = 3      # batch chunks in flight at once (one claude process each)
AI_RUN_MAX_MINUTES = 30         # AI budget for one /upload or /resume (plan 4.7)
AI_BUDGET_TRIP_ACTION = "write_flagged"  # or "stop": later periods wait for /resume
SUMMARY_FLAGGED_LINES = 40      # flagged rows listed in the summary; the rest go in an attachment
AI_CATEGORIZATION_ENABLED = False  # Enable after Session 2

# Rules beyond constants.py. The household's own accounts, by role, for rules
# that check who sent or received the money (IBANs; spaces and case ignored).
ACCOUNT_ROLES = {
    "savings": [],            # the savings account the pots live in
    "partner_personal": [],   # her personal account
    "user_personal": [],      # your personal accounts
}
# The household's own rules (git-ignored; written by scripts/apply_rule_draft.py).
LOCAL_RULES_PATH = "src/config/local_rules.tsv"

# Automation Schedule
AUTO_DOWNLOAD_ENABLED = False  # Enable after n8n is set up
AUTO_DOWNLOAD_TIME = "08:00"  # Run 1hr before daily reminder
AUTO_DOWNLOAD_DAYS_BACK = 7   # Download last 7 days of transactions

# API Configuration (for n8n integration)
API_ENABLED = True
API_HOST = "0.0.0.0"
API_PORT = 8000
API_SECRET_KEY = os.environ.get('API_SECRET_KEY', 'change-me-in-production')

# ─────────────────────────────────────────────────────────────────────────────
# DIRECTORY CREATION
# ─────────────────────────────────────────────────────────────────────────────

# Ensure directories exist
# Create absolute paths relative to project root
# __file__ = src/config/config_settings.py, so go up 3 levels to reach
# project root
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_upload_path = os.path.join(_project_root, UPLOAD_DIR)
_bank_download_path = os.path.join(_project_root, BANK_DOWNLOAD_DIR)
_bank_session_dir = os.path.dirname(
    os.path.join(_project_root, BANK_SESSION_FILE))

os.makedirs(_upload_path, exist_ok=True)
os.makedirs(_bank_download_path, exist_ok=True)
os.makedirs(_bank_session_dir, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Log the loaded configuration for debugging
logger = logging.getLogger(__name__)
logger.debug(f"🔧 Loaded Google Sheets config: {GSHEET_NAME_PATTERN=}, {GSHEET_DATA_START_ROW=}")
logger.debug(
    f"🔧 Loaded reminder config: time={DAILY_REMINDER_TIME}, channel={REMINDER_CHANNEL_ID}, users={len(MENTION_USER_IDS)}")

# ─────────────────────────────────────────────────────────────────────────────
# EXPORTS
# ─────────────────────────────────────────────────────────────────────────────

# Export all config variables for easy importing
__all__ = [
    "DISCORD_TOKEN",
    "DAILY_REMINDER_TIME",
    "REMINDER_CHANNEL_ID",
    "MENTION_USER_IDS",
    "CSV_DOWNLOAD_LINK",
    "TIMEZONE",
    "GOOGLE_SHEETS_ENABLED",
    "GOOGLE_OAUTH_CLIENT_PATH",
    "GOOGLE_OAUTH_TOKEN_PATH",
    "GSHEET_NAME_PATTERN",
    "GSHEET_TEMPLATE_ID",
    "GSHEET_FOLDER_ID",
    "GSHEET_AUTO_CREATE",
    "GSHEET_CREATE_NONADJACENT",
    "GSHEET_DATA_START_ROW",
    "SHEET_INDEX_PATH",
    "UPLOAD_LEDGER_PATH",
    "PERIOD_STATE_PATH",
    "RUNS_DIR",
    "PERIOD_BOUNDARY_MARKERS",
    "PERIOD_BOUNDARY_MIN_AMOUNT",
    "PERIOD_MIN_DAYS",
    "PERIOD_MAX_DAYS",
    "PERIOD_STEP_DAYS",
    "PERIOD_LABEL_SPLIT_DAY",
    "UPLOAD_DIR",
    # Automation configs
    "BANK_SCRAPER_ENABLED",
    "BANK_SESSION_FILE",
    "BANK_DOWNLOAD_DIR",
    "ASN_LOGIN_URL",
    "ASN_TRANSACTIONS_URL",
    "ASN_QR_TIMEOUT_SECONDS",
    "CLAUDE_API_KEY",
    "AI_CONFIDENCE_THRESHOLD",
    "AI_PER_TX_FALLBACK_LIMIT",
    "AI_MAX_PARALLEL_CHUNKS",
    "AI_RUN_MAX_MINUTES",
    "AI_BUDGET_TRIP_ACTION",
    "SUMMARY_FLAGGED_LINES",
    "AI_CATEGORIZATION_ENABLED",
    "ACCOUNT_ROLES",
    "LOCAL_RULES_PATH",
    "AUTO_DOWNLOAD_ENABLED",
    "AUTO_DOWNLOAD_TIME",
    "AUTO_DOWNLOAD_DAYS_BACK",
    "API_ENABLED",
    "API_HOST",
    "API_PORT",
    "API_SECRET_KEY"
]
