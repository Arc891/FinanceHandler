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
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/google_service_account.json")

# File Upload Configuration
UPLOAD_DIR = "data/uploads"
SESSION_DIR = "sessions"

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True) 
os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs("config", exist_ok=True)

# Export all config variables
__all__ = [
    "DISCORD_TOKEN",
    "DAILY_REMINDER_TIME", 
    "REMINDER_CHANNEL_ID",
    "MENTION_USER_IDS",
    "GOOGLE_SHEETS_ENABLED",
    "GOOGLE_CREDENTIALS_PATH",
    "UPLOAD_DIR",
    "SESSION_DIR"
]
