# Development Guide

## Getting Started

### Quick Setup

Run the setup script to get started quickly:

```bash
chmod +x setup.sh
./setup.sh
```

### Manual Setup

1. **Create virtual environment**

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate     # Windows
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Copy configuration**

   ```bash
   cp .env.example .env
   cp src/config_settings.example.py src/config_settings.py
   ```

4. **Configure your bot**
   - Edit `.env` with your Discord token
   - Edit `src/config_settings.py` with user IDs

5. **Set up Google Sheets (Optional)**
   - Create a Google Cloud Platform project
   - Enable Google Sheets API and Google Drive API
   - Create a service account and download the JSON key
   - Save the key as `src/config/google_service_account.json`
   - Share your Google Sheets with the service account email
   - Configure `GOOGLE_SHEETS_ENABLED=true` in your `.env` file

## Project Structure

```txt
FinanceAutomation/
├── .github/workflows/       # GitHub Actions CI/CD
├── src/                     # Source code
│   ├── bot.py              # Main bot entry point
│   ├── bot_commands.py     # Discord slash commands
│   ├── config_settings.py  # Configuration
│   ├── constants.py        # Categories and rules
│   ├── finance_core/       # Core business logic
│   │   ├── csv_helper.py   # CSV parsing utilities
│   │   ├── export.py       # Export functionality
│   │   ├── google_sheets.py # Google Sheets integration
│   │   ├── session_management.py # Session persistence
│   │   └── ui/             # Discord UI components
│   │       └── transaction_prompt.py # Transaction categorization UI
│   └── config/             # Configuration files
│       ├── google_service_account.json # Google API credentials (not in git)
│       └── spaarpot_uuid_map.py # Savings account mapping
├── data/                   # Runtime data (auto-created)
│   ├── sessions/           # User session files
│   └── uploads/            # Uploaded CSV files
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── .gitignore             # Git ignore rules
├── setup.sh               # Development setup script
├── LICENSE                # MIT License
└── README.md              # Project documentation
```

## Code Style

### Python Standards

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Add docstrings to functions and classes
- Keep line length under 127 characters

### Naming Conventions

- **Files**: `snake_case.py`
- **Classes**: `PascalCase`
- **Functions/Variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`

### Example Code Style

```python
from typing import List, Dict, Any
import discord

class TransactionProcessor:
    """Handles processing of financial transactions."""
    
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.transactions: List[Dict[str, Any]] = []
    
    async def process_transaction(self, transaction: Dict[str, Any]) -> bool:
        """
        Process a single transaction.
        
        Args:
            transaction: Transaction data dictionary
            
        Returns:
            True if processing was successful
        """
        # Implementation here
        pass
```

## Discord Bot Development

### Setting Up a Test Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section and create a bot
4. Copy the token to your `.env` file
5. Enable these intents:
   - Message Content Intent
   - Server Members Intent

### Bot Permissions

Your bot needs these permissions:

- Send Messages
- Use Slash Commands
- Read Message History
- Attach Files
- Use External Emojis

### Testing Commands

Use a test server to avoid affecting production:

```python
# In config_settings.py
TEST_GUILD_ID = 123456789  # Your test server ID

# In bot.py (for testing only)
@bot.tree.sync(guild=discord.Object(id=TEST_GUILD_ID))
```

## Database and Sessions

### Session Storage

Sessions are stored as JSON files in the `sessions/` directory:

```python
# Session file structure
{
    "remaining": [...],    # Unprocessed transactions
    "income": [...],       # Categorized income
    "expenses": [...]      # Categorized expenses
}
```

### Adding New Data Fields

When adding new fields to transactions:

1. Update the CSV parser in `csv_helper.py`
2. Update the UI in `transaction_prompt.py`
3. Update session management if needed
4. Test with existing session files

## Testing

### Running Tests

```bash
# Test imports
cd src && python -c "import bot_commands; print('✅ Imports OK')"

# Test configuration
python -c "from config_settings import *; print('✅ Config OK')"

# Test CSV processing
python -c "from finance_core.csv_helper import load_transactions_from_csv"

# Test Google Sheets integration (with credentials)
python -c "from finance_core.google_sheets import GoogleSheetsExporter; print('✅ Google Sheets OK')"
```

### Testing Google Sheets Integration

To test Google Sheets functionality:

1. Set up a test Google Sheet
2. Create test data:

   ```python
   test_income = [{"date": "2024-01-01", "amount": 100.0, "category": "Salary"}]
   test_expenses = [{"date": "2024-01-01", "amount": -50.0, "category": "Food"}]
   ```

3. Test the export:

   ```python
   from finance_core.google_sheets import export_to_google_sheets
   export_to_google_sheets(test_income, test_expenses)
   ```

### Manual Testing

1. Start the bot: `cd src && python bot.py`
2. Use `/upload` with a test CSV file
3. Test the categorization UI
4. Test session resume functionality

## Data Directory Structure

The bot uses a dedicated `data/` directory for runtime files, keeping source code separate from user data:

```txt
data/
├── sessions/           # User session persistence files
│   └── {user_id}.json # Session data for resuming interrupted processing
└── uploads/            # User-uploaded CSV files
    └── {user_id}_{filename}.csv
```

### Path Configuration

All directory paths are configured in `src/config_settings.py`:

```python
UPLOAD_DIR = "data/uploads"    # Relative to project root
SESSION_DIR = "data/sessions"  # Relative to project root
```

The session management system automatically calculates absolute paths from the project root, ensuring consistent behavior regardless of the working directory when the bot is started.

### Working Directory Independence

The bot can be started from any directory within the project. The path resolution system:

1. Locates the project root using the source file locations
2. Creates absolute paths for data directories
3. Automatically creates missing directories

This means all these commands work equivalently:

```bash
# From project root
python src/bot.py

# From src directory
cd src
python bot.py

# From any subdirectory
cd src/finance_core
python ../bot.py
```

## Adding New Features

### Adding New Categories

1. Edit `src/constants.py`:

   ```python
   class ExpenseCategory(str, Enum):
       NEW_CATEGORY = ("New Category", r"new|category")
   ```

2. Add auto-categorization rules:

   ```python
   CATEGORIZATION_RULES_EXPENSE = {
       r"pattern": ("Description", ExpenseCategory.NEW_CATEGORY),
   }
   ```

### Adding New Commands

1. Add to `src/bot_commands.py`:

   ```python
   @app_commands.command(name="newcommand", description="Description")
   async def new_command(self, interaction: discord.Interaction):
       await interaction.response.send_message("Hello!")
   ```

2. Test the command
3. Update documentation

### Adding New UI Components

1. Create new view in `src/finance_core/ui/`
2. Follow Discord.py UI patterns
3. Add timeout handling
4. Test interaction flows

## Deployment

### Production Checklist

- [ ] Environment variables set correctly
- [ ] Discord bot token secured
- [ ] Proper file permissions
- [ ] Log rotation configured
- [ ] Error monitoring in place
- [ ] Backup strategy for sessions

### Environment Variables

```bash
# Required
DISCORD_TOKEN=your_production_token

# Optional
REMINDER_CHANNEL_ID=channel_id
DAILY_REMINDER_TIME=09:00
LOG_LEVEL=INFO
```

### Running in Production

```bash
# Using systemd (recommended)
sudo systemctl start discord-finance-bot

# Using screen/tmux
screen -S finance-bot
cd /path/to/FinanceAutomation/src
python bot.py

# Using nohup
nohup python bot.py > bot.log 2>&1 &
```

## Troubleshooting

### Common Issues

1. **Import Errors**
   - Check virtual environment activation
   - Verify all dependencies installed
   - Check Python path

2. **Discord Connection Issues**
   - Verify bot token
   - Check bot permissions
   - Ensure intents are enabled

3. **CSV Processing Issues**
   - Check CSV format matches expected structure
   - Verify file encoding (UTF-8)
   - Check for missing columns

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Getting Help

1. Check the logs for error messages
2. Verify configuration settings
3. Test with minimal examples
4. Check Discord.py documentation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

### Pull Request Guidelines

- Include a clear description
- Add tests if applicable
- Update documentation
- Follow code style guidelines
- Keep commits focused and atomic
