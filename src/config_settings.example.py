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
# DIRECTORY CREATION
# ─────────────────────────────────────────────────────────────────────────────

# Ensure directories exist
# Create absolute paths relative to project root
_project_root = os.path.dirname(os.path.dirname(__file__))
_upload_path = os.path.join(_project_root, UPLOAD_DIR)
_config_path = os.path.join(os.path.dirname(__file__), "config")
os.makedirs(_upload_path, exist_ok=True)
os.makedirs(_config_path, exist_ok=True)

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
    "SESSION_DIR"
]
