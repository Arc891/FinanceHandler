# Discord Finance Bot

A Discord bot for automated processing and categorization of financial transactions from CSV exports.

## Features

- 🤖 **Modern Discord Bot** with slash commands
- � **CSV Transaction Processing** from bank exports
- 🏷️ **Interactive Categorization** with Discord UI
- 💾 **Session Management** for resuming interrupted processes
- ⏰ **Daily Reminders** for transaction processing
- � **Auto-categorization** with customizable rules

## Commands

- `/upload` - Upload a CSV file to start processing transactions
- `/resume` - Resume a previously paused session
- `/status` - Check your current processing progress
- `/cancel` - Cancel and clear your current session

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
   # Copy environment template
   cp .env.example .env
   
   # Edit .env with your values
   nano .env
   ```

5. **Set up Discord Bot**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to "Bot" section
   - Copy the token to your `.env` file
   - Enable required intents: Message Content, Server Members

6. **Run the bot**
   ```bash
   cd src
   python bot.py
   ```

## Configuration

### Environment Variables (.env)

```env
# Discord Bot Token (required)
DISCORD_TOKEN=your_discord_bot_token_here

# Channel ID for daily reminders (optional)
REMINDER_CHANNEL_ID=your_channel_id_here

# Daily reminder time (optional, default: 09:00)
DAILY_REMINDER_TIME=09:00
```

### User Mentions

Edit `src/config_settings.py` to add Discord user IDs for mentions:

```python
MENTION_USER_IDS: List[int] = [
    123456789012345678,  # Your Discord user ID
    987654321098765432,  # Other user IDs
]
```

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
- Use environment variables for sensitive configuration
- Keep your `.env` file in `.gitignore`
- Regularly rotate your bot token if compromised

## Support

If you encounter issues:

1. Check the bot logs for error messages
2. Verify your Discord bot permissions
3. Ensure your CSV format matches the expected structure
4. Check that all required environment variables are set

## Changelog

See [CHANGES.md](CHANGES.md) for detailed change history.

```python
MENTION_USER_IDS: List[int] = [
    123456789012345678,  # Replace with actual Discord user IDs
    987654321098765432,
]
```

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

### Daily Reminders

The bot will send daily reminders at 09:00 (configurable) to upload CSV files for processing.

## File Structure

```
src/
├── bot.py                    # Main bot file
├── bot_commands.py           # Slash command definitions
├── config.py                 # Configuration settings
├── constants.py              # Category enums and rules
├── asnexport.py             # Legacy CSV processing
└── finance_core/
    ├── csv_helper.py         # CSV loading and normalization
    ├── export.py             # Main processing logic
    ├── session_management.py # Session persistence
    └── ui/
        └── transaction_prompt.py # Interactive UI components
```

## Configuration

- **Daily reminder time**: Edit `DAILY_REMINDER_TIME` in `config.py`
- **File upload directory**: Edit `UPLOAD_DIR` in `config.py`
- **Transaction categories**: Edit `ExpenseCategory` and `IncomeCategory` in `constants.py`
- **Auto-categorization rules**: Edit `CATEGORIZATION_RULES_*` in `constants.py`

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
pip install discord.py python-dotenv
```

### Bot Not Responding

1. Check that the bot token is correct in `.env`
2. Ensure the bot has proper permissions in your Discord server
3. Check the console for error messages
