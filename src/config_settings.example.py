# config_settings.py - Discord Bot Configuration Template
# Copy this file to config_settings.py and fill in your values

import os
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Discord Bot Configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "your_discord_token_here")

# Daily Reminder Configuration  
DAILY_REMINDER_TIME = os.getenv("DAILY_REMINDER_TIME", "09:00")  # 24-hour format (HH:MM)
REMINDER_CHANNEL_ID = int(os.getenv("REMINDER_CHANNEL_ID", "0"))  # Replace with your channel ID
MENTION_USER_IDS: List[int] = [
    # Add Discord user IDs to mention in reminders
    # Example: 123456789012345678
]

# Google Sheets Configuration
GOOGLE_SHEETS_ENABLED = os.getenv("GOOGLE_SHEETS_ENABLED", "true").lower() == "true"
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "src/config/google_service_account.json")
GSHEET_NAME = os.getenv("GSHEET_NAME", "Test Automation Sheet").strip("\"'")
GSHEET_TAB = os.getenv("GSHEET_TAB", "Blad1").strip("\"'")

# Sheet Layout Configuration
# These settings define which row the transaction data should start from
# Adjust these based on your sheet structure (headers, instructions, etc.)
GSHEET_EXPENSE_START_ROW = int(os.getenv("GSHEET_EXPENSE_START_ROW", "2"))  # Row for first expense transaction
GSHEET_INCOME_START_ROW = int(os.getenv("GSHEET_INCOME_START_ROW", "2"))   # Row for first income transaction

# File Upload Configuration
UPLOAD_DIR = "data/uploads"

# Session Configuration  
SESSION_DIR = "data/sessions"

# Ensure directories exist
# Create absolute paths relative to project root
_project_root = os.path.dirname(os.path.dirname(__file__))
_upload_path = os.path.join(_project_root, UPLOAD_DIR)
_config_path = os.path.join(os.path.dirname(__file__), "config")
os.makedirs(_upload_path, exist_ok=True)
os.makedirs(_config_path, exist_ok=True)

# Export all config variables
__all__ = [
    "DISCORD_TOKEN",
    "DAILY_REMINDER_TIME", 
    "REMINDER_CHANNEL_ID",
    "MENTION_USER_IDS",
    "GOOGLE_SHEETS_ENABLED",
    "GOOGLE_CREDENTIALS_PATH",
    "GSHEET_NAME",
    "GSHEET_TAB",
    "GSHEET_EXPENSE_START_ROW",
    "GSHEET_INCOME_START_ROW",
    "UPLOAD_DIR",
    "SESSION_DIR"
]
