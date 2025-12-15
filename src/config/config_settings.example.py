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
CSV_DOWNLOAD_LINK = ""  # Example: "https://bankname.com/export" or "https://yourdomain.com/csv"

# Timezone for reminder scheduling (uses system TZ environment variable, defaults to UTC)
TIMEZONE = os.environ.get('TZ', 'UTC')

# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE SHEETS CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Enable/disable Google Sheets integration
GOOGLE_SHEETS_ENABLED = True

# Path to Google service account credentials JSON file
GOOGLE_CREDENTIALS_PATH = "src/config/google_service_account.json"

# Google Sheets configuration
GSHEET_NAME = "Test Automation Sheet"
GSHEET_TAB = "Blad1"

# Sheet Layout Configuration
# The row number where transaction data starts (after headers)
GSHEET_EXPENSE_START_ROW = 2  # Row for first expense transaction
GSHEET_INCOME_START_ROW = 2   # Row for first income transaction

# ─────────────────────────────────────────────────────────────────────────────
# FILE STORAGE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# File Upload Configuration
UPLOAD_DIR = "data/uploads"

# Session Configuration
SESSION_DIR = "data/sessions"

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
CLAUDE_MODEL = "claude-3-5-haiku-20241022"
AI_CONFIDENCE_THRESHOLD = 0.75  # Min confidence for auto-approval (0.0-1.0)
AI_CATEGORIZATION_ENABLED = False  # Enable after Session 2

# Automation Schedule
AUTO_DOWNLOAD_ENABLED = False  # Enable after n8n is set up
AUTO_DOWNLOAD_TIME = "08:00"  # Run 1hr before daily reminder
AUTO_DOWNLOAD_DAYS_BACK = 7   # Download last 7 days of transactions

# Discord Approval Configuration (Session 3 - will be configured later)
APPROVAL_CHANNEL_ID = 0  # Channel for approval requests
APPROVAL_WEBHOOK_URL = ""  # Webhook for sending approvals
PENDING_APPROVALS_FILE = "data/pending_approvals.json"

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
_project_root = os.path.dirname(os.path.dirname(__file__))
_upload_path = os.path.join(_project_root, UPLOAD_DIR)
_config_path = os.path.join(os.path.dirname(__file__), "config")
_bank_download_path = os.path.join(_project_root, BANK_DOWNLOAD_DIR)
_bank_session_dir = os.path.dirname(os.path.join(_project_root, BANK_SESSION_FILE))

os.makedirs(_upload_path, exist_ok=True)
os.makedirs(_config_path, exist_ok=True)
os.makedirs(_bank_download_path, exist_ok=True)
os.makedirs(_bank_session_dir, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Log the loaded configuration for debugging
logger = logging.getLogger(__name__)
logger.debug(f"🔧 Loaded Google Sheets config: {GSHEET_NAME=}, {GSHEET_TAB=}")
logger.debug(f"🔧 Loaded row config: expense_start={GSHEET_EXPENSE_START_ROW}, income_start={GSHEET_INCOME_START_ROW}")
logger.debug(f"🔧 Loaded reminder config: time={DAILY_REMINDER_TIME}, channel={REMINDER_CHANNEL_ID}, users={len(MENTION_USER_IDS)}")

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
    "GOOGLE_CREDENTIALS_PATH",
    "GSHEET_NAME",
    "GSHEET_TAB",
    "GSHEET_EXPENSE_START_ROW",
    "GSHEET_INCOME_START_ROW",
    "UPLOAD_DIR",
    "SESSION_DIR",
    # Automation configs
    "BANK_SCRAPER_ENABLED",
    "BANK_SESSION_FILE",
    "BANK_DOWNLOAD_DIR",
    "ASN_LOGIN_URL",
    "ASN_TRANSACTIONS_URL",
    "ASN_QR_TIMEOUT_SECONDS",
    "CLAUDE_API_KEY",
    "CLAUDE_MODEL",
    "AI_CONFIDENCE_THRESHOLD",
    "AI_CATEGORIZATION_ENABLED",
    "AUTO_DOWNLOAD_ENABLED",
    "AUTO_DOWNLOAD_TIME",
    "AUTO_DOWNLOAD_DAYS_BACK",
    "APPROVAL_CHANNEL_ID",
    "APPROVAL_WEBHOOK_URL",
    "PENDING_APPROVALS_FILE",
    "API_ENABLED",
    "API_HOST",
    "API_PORT",
    "API_SECRET_KEY"
]
