# config.py - Discord Bot Configuration

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

# File Upload Configuration
UPLOAD_DIR = "data/uploads"
SESSION_DIR = "sessions"

# Ensure directories exist
os.makedirs(UPLOAD_DIR, exist_ok=True) 
os.makedirs(SESSION_DIR, exist_ok=True)

# Export all config variables
__all__ = [
    "DISCORD_TOKEN",
    "DAILY_REMINDER_TIME", 
    "REMINDER_CHANNEL_ID",
    "MENTION_USER_IDS",
    "UPLOAD_DIR",
    "SESSION_DIR"
]
