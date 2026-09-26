"""
Startup self-check for config/config_settings.py (plan 4.10).

bot.py calls check_required_settings() before it imports anything from the
config, so a config that predates the multi-month upload (the Pi's, before
Phase 4 step 3) stops the bot with one line naming what is missing, instead
of an ImportError or a wrong default halfway through a run.
"""

import importlib
import sys

REQUIRED_SETTINGS = (
    # Discord
    "DISCORD_TOKEN",
    "DAILY_REMINDER_TIME",
    "REMINDER_CHANNEL_ID",
    "MENTION_USER_IDS",
    "CSV_DOWNLOAD_LINK",
    "TIMEZONE",
    # Google (4.2, 4.4)
    "GOOGLE_AUTH_MODE",
    "GOOGLE_OAUTH_CLIENT_PATH",
    "GOOGLE_OAUTH_TOKEN_PATH",
    "GSHEET_NAME_PATTERN",
    "GSHEET_TEMPLATE_ID",
    "GSHEET_FOLDER_ID",
    "GSHEET_AUTO_CREATE",
    "GSHEET_CREATE_NONADJACENT",
    "GSHEET_DATA_START_ROW",
    "SHEET_INDEX_PATH",
    # Periods and the ledger (4.3, 4.6)
    "PERIOD_BOUNDARY_MARKERS",
    "PERIOD_BOUNDARY_MIN_AMOUNT",
    "PERIOD_MIN_DAYS",
    "PERIOD_MAX_DAYS",
    "PERIOD_STEP_DAYS",
    "PERIOD_LABEL_SPLIT_DAY",
    "PERIOD_STATE_PATH",
    "UPLOAD_LEDGER_PATH",
    # AI (4.7, 4.9)
    "AI_CONFIDENCE_THRESHOLD",
    "AI_RUN_MAX_MINUTES",
    "AI_PER_TX_FALLBACK_LIMIT",
    "AI_MAX_PARALLEL_CHUNKS",
    "AI_BUDGET_TRIP_ACTION",
)


def check_required_settings(module_name: str = "config.config_settings",
                            required=REQUIRED_SETTINGS) -> None:
    """Exit with one line on stderr unless every required key is defined."""
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(f"config: cannot import {module_name} ({exc}); copy "
              "src/config/config_settings.example.py and fill it in",
              file=sys.stderr)
        sys.exit(1)
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        print(f"config: {module_name} is missing {', '.join(missing)}; "
              "copy them from src/config/config_settings.example.py",
              file=sys.stderr)
        sys.exit(1)
