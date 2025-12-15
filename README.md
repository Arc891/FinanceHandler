# Discord Finance Automation Bot

## Features

- 🤖 **Modern Discord Bot** with slash commands
- 📄 **CSV Transaction Processing** from bank exports
- 🏷 **Interactive Categorization** with Discord UI
- 💾 **Session Management** for resuming interrupted processes
- ⏰ **Daily Reminders** for transaction processing
- 🎯 **Auto-categorization** with customizable rules

## Commands

- `/upload` - Upload a CSV file to start processing transactions
- `/resume` - Resume a previously paused session
- `/status` - Check your current processing progress
- `/cancel` - Cancel and clear your current session
- `/cached` - View and process cached transactions

## Setup

### Prerequisites

- Python 3.8+
- Discord Bot Token
- Virtual environment (recommended)

### Installation

1. **Clone the repository**

   ```bash
   git clone <your-repo-url>
   cd FinanceAutomation
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the bot**

   ```bash
   # Copy configuration template
   cp src/config/config_settings.example.py src/config/config_settings.py
   
   # Edit config_settings.py with your values
   nano src/config/config_settings.py
   ```

5. **Set up Discord Bot**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to "Bot" section
   - Copy the token to your `src/config/config_settings.py` file
   - Enable required intents: Message Content, Server Members

6. **Set up Google Sheets (Optional)**
   
   If you want to export transactions to Google Sheets:
   
   a. Go to [Google Cloud Console](https://console.cloud.google.com/)
   b. Create a new project or select an existing one
   c. Enable the Google Sheets API and Google Drive API
   d. Go to "Credentials" → "Create Credentials" → "Service Account"
   e. Download the JSON key file
   f. Save it as `src/config/google_service_account.json`
   g. Share your Google Sheet with the service account email
   h. Update your `src/config/config_settings.py` file with Google Sheets configuration

7. **Run the bot**

   ```bash
   cd src
   python bot.py
   ```

## Configuration

### Main Configuration (config_settings.py)

Edit `src/config/config_settings.py` to configure the bot:

```python
# Discord Bot Token (required)
DISCORD_TOKEN = "your_discord_bot_token_here"

# Daily Reminder Configuration
DAILY_REMINDER_TIME = "09:00"  # 24-hour format
REMINDER_CHANNEL_ID = 1234567890123456789  # Channel ID for reminders
MENTION_USER_IDS = [
    123456789012345678,  # Your Discord user ID
    987654321098765432,  # Other user IDs
]

# CSV Download Link (optional)
CSV_DOWNLOAD_LINK = ""  # URL where users can download CSV files

# Google Sheets Configuration (optional)
GOOGLE_SHEETS_ENABLED = True
GSHEET_NAME = "Your Sheet Name"
GSHEET_TAB = "Your Tab Name"
```

### User Mentions

Add Discord user IDs to the `MENTION_USER_IDS` list in `config_settings.py` for daily reminder mentions.

## CSV Format

The bot expects CSV files with the following columns (ASN Bank format):

- Date
- Account IBAN
- Counterparty IBAN
- Counterparty Name
- Transaction Amount
- Currency
- Transaction Code
- Remittance Information

## Customization

### Categories

Edit `src/constants.py` to customize income and expense categories:

```python
class ExpenseCategory(str, Enum):
    FOOD = ("Food", r"food|restaurant|grocery")
    TRANSPORT = ("Transport", r"transport|uber|taxi")
    # Add your categories...
```

### Auto-categorization Rules

Add regex patterns in `src/constants.py`:

```python
CATEGORIZATION_RULES_EXPENSE = {
    r"JUMBO|PICNIC|LIDL": ("Groceries", ExpenseCategory.FOOD),
    r"Shell|BP|Texaco": ("Fuel", ExpenseCategory.TRANSPORT),
    # Add your rules...
}
```

## Security

- Never commit your Discord bot token or API keys
- Keep your `config_settings.py` file secure
- Add `src/config/config_settings.py` to `.gitignore` if it contains sensitive data
- Regularly rotate your bot token if compromised

## Support

If you encounter issues:

1. Check the bot logs for error messages
2. Verify your Discord bot permissions
3. Ensure your CSV format matches the expected structure
4. Check that all required configuration is set in `src/config/config_settings.py`

## Changelog

See [docs/CHANGES.md](docs/CHANGES.md) for detailed change history.

### 5. Run the Bot

```bash
cd src
python bot.py
```

## Usage

### Slash Commands

- `/upload` - Upload a CSV file to start processing transactions
- `/status` - Check your current processing session status
- `/resume` - Resume a previously paused session
- `/cancel` - Cancel and clear your current session
- `/cached` - View and process cached transactions

### Daily Reminders

The bot will send daily reminders at 09:00 (configurable) to upload CSV files for processing.

## File Structure

```txt
/
├── README.md                 # Project readme
├── CLAUDE.md                 # Claude Code instructions
├── docs/                     # Documentation
│   ├── CHANGES.md           # Changelog
│   ├── DEVELOPMENT.md       # Development guide
│   └── automation/          # Automation docs
├── scripts/                  # Utility scripts
│   ├── setup.sh             # Quick setup
│   ├── run.sh               # Docker deployment
│   └── browsercode/         # Bank automation
├── src/                      # Source code
│   ├── bot.py               # Main entry point
│   ├── bot_commands.py      # Slash commands
│   ├── constants.py         # Categories & rules
│   ├── config/              # Configuration (NOT in git)
│   │   ├── config_settings.py
│   │   └── google_service_account.json
│   ├── api/                 # Automation API
│   ├── automation/          # Bank scraper
│   └── finance_core/        # Core finance logic
│       ├── csv_helper.py
│       ├── export.py
│       ├── google_sheets.py
│       ├── session_management.py
│       └── ui/
└── data/                     # Runtime data (NOT in git)
    ├── sessions/            # User sessions
    ├── uploads/             # CSV uploads
    ├── bank_downloads/      # Downloaded CSVs
    └── browser_profile/     # Browser session
```

## Environment Configuration

- **Daily reminder time**: Edit `DAILY_REMINDER_TIME` in `config_settings.py`
- **Upload directory**: Edit `UPLOAD_DIR` in `config_settings.py` (default: `data/uploads`)
- **Session directory**: Edit `SESSION_DIR` in `config_settings.py` (default: `data/sessions`)
- **Transaction categories**: Edit `ExpenseCategory` and `IncomeCategory` in `constants.py`
- **Auto-categorization rules**: Edit `CATEGORIZATION_RULES_*` in `constants.py`

### Data Directory Structure

The bot uses a dedicated `data/` directory for runtime files:

- `data/sessions/` - User session files for resuming interrupted processing
- `data/uploads/` - Uploaded CSV files from Discord

These directories are automatically created when the bot starts. This structure keeps source code separate from runtime data.

## Troubleshooting

### Import Errors

Make sure you're running the bot from the `src/` directory:

```bash
cd src
python bot.py
```

### Missing Dependencies

Install missing packages:

```bash
pip install discord.py
```

### Bot Not Responding

1. Check that the bot token is correct in `src/config/config_settings.py`
2. Ensure the bot has proper permissions in your Discord server
3. Check the console for error messages
