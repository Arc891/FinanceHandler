# Development Guide

## Getting Started

### Quick Setup

Run the setup script from the project root:

```bash
chmod +x scripts/setup.sh
scripts/setup.sh
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
   pip install -r requirements.txt -r requirements-dev.txt
   ```

   `requirements-dev.txt` holds the test tooling (pytest, pytest-asyncio).

3. **Copy configuration**

   ```bash
   cp src/config/config_settings.example.py src/config/config_settings.py
   ```

4. **Configure your bot**
   - Edit `src/config/config_settings.py` with your Discord token, channel and household user IDs
   - The example is the reference for every key; `src/config_check.py` lists the required ones, and `bot.py` refuses to start (one line naming the missing keys) until they are all present

5. **Set up Google access** (see [Google access](#google-access) below)
   - Put the OAuth client JSON in `data/google/oauth_client.json`
   - Run `venv/bin/python scripts/google_login.py` once to create `data/google/authorized_user.json`
   - Seed the month index: `venv/bin/python scripts/register_sheets.py seed` (or `add` / `paste`)

## Google access

The bot reads and writes the monthly spreadsheets as the user's own Google account, through an OAuth token. The service account is no longer used by the bot: its Drive quota is 0, so it cannot create a month from the template.

- **The OAuth client**: a Desktop client in the Google Cloud project, consent screen External and published to production, with the scopes `spreadsheets` and `drive.file` only. Every other `drive.*` scope is restricted and would need a paid security assessment, so do not add one; `tests/test_google_auth.py` fails if the code asks for more. Click-by-click steps: `docs/plans/PHASE0_USER_SETUP.md`.
- **The login**, once, on the workstation, in your own terminal (not through an AI session, so the token never lands in a conversation):

  ```bash
  venv/bin/python scripts/google_login.py
  ```

  It prints a URL: open the whole URL in a private browser window, sign in with the account that owns the `Financiën` folder, accept the "Google hasn't verified this app" warning (Advanced > Go to Finance Bot) and tick both scopes. The token is refused unless exactly those two scopes were granted, and is written with mode 0600 to `GOOGLE_OAUTH_TOKEN_PATH` (`data/google/authorized_user.json`).
- **On the Pi**: copy `authorized_user.json` and `oauth_client.json` to `data/google/` (owner `pi`, mode 0600). `run.sh` refuses to deploy without the token.
- **When the token stops working** (revoked, expired): a run stops with "Google authorisation failed" and keeps its state. Run `google_login.py` again on the workstation, copy the token, then `/resume`.
- **Inspection scripts** (`sheet_shape.py`, `eval_categoriser.py`) still read with the service account, read-only, from `--credentials` (default `src/config/google_service_account.json`).

## Privacy when inspecting real data

The sheets and exports hold the household's real transactions. Anything that reads them for development prints structure and counts only:

- `scripts/sheet_shape.py` prints tab names, header rows, row counts, date ranges, category counts and formulas with their numbers and texts masked; never an amount, description, counterparty or IBAN.
- `scripts/eval_categoriser.py`, `rule_coverage.py`, `apply_rule_draft.py`, `retry_failed_transactions.py` and `time_ai_chunk.py` print counts, percentages, category names and anonymous group ids; `seed_state.py` prints dates and labels only. Where names or amounts are needed (rule drafts), they go to a file with mode 0600 for the user to read.
- `scripts/backfill_notes.py` is an owner-run exception: it compares private transaction rows and the original export in memory, but its output is counts only. Do not run its private matching from an agent session without approval, and do not share the export or a debug trace.
- Log lines carry labels, statuses and counts, never a name, description, remittance text or amount; `tests/test_log_privacy.py` enforces this for the categorisation path and the pipeline.
- Do not open `data/`, real CSV exports or `src/config/local_rules.tsv` while developing. Use the anonymised fixture `tests/fixtures/multi_month.csv`, made with `scripts/make_fixture.py`, or ask the user to run a script and paste its output.

A new inspection script follows the same rule, with a test that no name, remittance, amount or date from its input reaches its output.

## Project Structure

```txt
FinanceAutomation/
├── .github/workflows/       # GitHub Actions CI/CD
├── .pre-commit-config.yaml  # Pre-commit hooks configuration
├── src/                     # Source code
│   ├── bot.py              # Main bot entry point (config self-check first)
│   ├── bot_commands.py     # Discord slash commands
│   ├── config_check.py     # Required config keys
│   ├── constants.py        # Categories, rule tables, conditional rules
│   ├── config/             # Configuration files
│   │   ├── config_settings.py      # Main configuration (not in git)
│   │   ├── local_rules.tsv         # The household's own rules (not in git)
│   │   ├── google_service_account.json # Service account for inspection scripts (not in git)
│   │   └── spaarpot_uuid_map.py    # Savings account mapping
│   ├── automation/         # Bank automation & AI
│   │   ├── bank_scraper.py         # Playwright scraper for ASN Bank
│   │   ├── ai_categorizer.py       # Batch AI categorisation
│   │   ├── claude_provider.py      # Claude CLI/API abstraction
│   │   └── data_anonymizer.py      # PII removal before AI calls
│   ├── api/                # HTTP API for n8n integration
│   │   └── automation_endpoints.py # FastAPI endpoints
│   └── finance_core/       # Core business logic
│       ├── export.py               # Upload pipeline (process_upload, resume, cancel, sort, status)
│       ├── run_state.py            # Per-run state files
│       ├── csv_helper.py           # CSV parsing
│       ├── periods.py              # Split into financial months (pure)
│       ├── period_state.py         # The period anchor file
│       ├── sheet_index.py          # Month -> spreadsheet index file
│       ├── sheet_registry.py       # Resolve or create a month's spreadsheet
│       ├── sheet_writer.py         # Append, read, compact, sort, remove rows
│       ├── row_tuple.py            # Canonical row comparison form
│       ├── ledger.py               # Dedup record and write audit
│       ├── google_auth.py          # OAuth credentials
│       ├── google_retry.py         # Bounded retry for idempotent calls
│       ├── google_sheets.py        # Row formatting for the sheet
│       ├── categorization_engine.py # Rules + batch AI
│       ├── categorization_rules.py # The rule pass
│       ├── local_rules.py          # Reads local_rules.tsv
│       ├── rule_conditions.py      # Rule condition syntax
│       ├── tx_features.py          # Row features for rules
│       ├── pot_links.py            # Pot hints for the AI
│       ├── flagging.py             # Placeholder category and marks
│       ├── discord_threads.py      # The user's progress thread
│       └── config_access.py        # Late config access, project paths
├── data/                   # Runtime data (not in git, see below)
├── docs/                   # Documentation
│   ├── plans/              # MULTI_MONTH_UPLOAD_PLAN.md, PHASE0_USER_SETUP.md
│   └── automation/         # Automation-specific docs
├── scripts/                # Tools; each script's docstring is its manual
├── tests/                  # pytest suite; fixtures/ holds anonymised CSVs
├── pytest.ini
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Test dependencies
├── run.sh                  # Docker deployment script
└── README.md               # Project documentation
```

## Pre-commit Hooks

This project uses [pre-commit](https://pre-commit.com/) for automated code quality checks.

### Setup

```bash
pip install pre-commit
pre-commit install
```

### What Gets Checked

On every commit:
- **flake8**: Critical Python errors (syntax, undefined names)
- **trailing-whitespace**: Removes trailing whitespace
- **end-of-file-fixer**: Ensures files end with newline
- **check-yaml/json**: Validates YAML and JSON files
- **detect-private-key**: Prevents accidental key commits

### Running Manually

```bash
# Run on all files
pre-commit run --all-files

# Run specific hook
pre-commit run flake8 --all-files
```

### Skipping Hooks (Emergency Only)

```bash
git commit --no-verify -m "message"
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
4. Copy the token to your `src/config/config_settings.py` file
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
- Create Private Threads and Send Messages in Threads: progress and summaries go to a private `Approvals-<name>` thread in the `REMINDER_CHANNEL_ID` channel

Every command answers only users in `MENTION_USER_IDS`; add your test account there.

### Testing Commands

Use a test server to avoid affecting production:

```python
# In config_settings.py
TEST_GUILD_ID = 123456789  # Your test server ID

# In bot.py (for testing only)
@bot.tree.sync(guild=discord.Object(id=TEST_GUILD_ID))
```

A test bot with the real config writes to the real monthly sheets. Point `SHEET_INDEX_PATH`, `UPLOAD_LEDGER_PATH`, `PERIOD_STATE_PATH` and `RUNS_DIR` at scratch files, and keep `GSHEET_AUTO_CREATE = False` unless you mean to create a month.

## Run State and Data Files

There are no per-user sessions any more. An upload is a run, identified by its `upload_id`:

- `data/runs/<upload_id>.json` holds the run: its files, the period split, and per financial month its status (`split`, `resolved`, `categorised`, `appending`, `written`, `failed`), its rows until they are written, and its flagged rows with the AI guess that was not used. It is written atomically after every status change, so `/resume` can finish any interrupted run. A run closes as `complete`, `abandoned` (`/cancel`) or `refused` (the split was rejected).
- `data/upload_ledger.json` is the dedup record and the write audit (`ledger.py`). `scripts/undo_upload.py <upload_id>` reverses a run from its audit.
- `data/period_state.json` holds the period anchor and its history (`period_state.py`).
- `data/sheet_index.json` maps `MM/YYYY` to a spreadsheet id and is authoritative: the bot cannot search Drive, so a lost index is rebuilt only by `register_sheets.py` or `/months register`.

### Adding New Data Fields

When adding new fields to transactions:

1. Update the CSV parser in `csv_helper.py`
2. If the field reaches the AI, add it to the anonymiser (`automation/data_anonymizer.py`) and its tests
3. If a rule should check it, add it to `tx_features.py` and `rule_conditions.py`
4. Keep it out of log lines (`tests/test_log_privacy.py`)
5. Run states from before the change hold rows without the field; handle its absence

## Testing

### Running Tests

```bash
venv/bin/python -m pytest -q
```

`pytest.ini` limits collection to `tests/`, puts `src` and `scripts` on the path and runs async tests without markers (`asyncio_mode = auto`). The suite needs no network and no Google account:

- `tests/fakes.py` fakes the Google layer (`FakeWorkbooks`, `FakeSpreadsheet`); `tests/pipeline_env.py` is the pipeline harness (fake engine and clock), which can crash a run at an exact point and resume it; `tests/test_bot_commands.py` uses fake Discord interactions.
- `tests/fixtures/multi_month.csv` is an anonymised export (390 rows, five financial months) made with `scripts/make_fixture.py`.
- Tests come first: a change to behaviour starts with a failing test. Where the plan names a scenario, the test is derived from it.

### Testing Against Google

`scripts/sandbox_check.py` runs the Google layer against the real APIs on a synthetic month `SANDBOX Maandelijks Budget 12/2099`: create from the template with the full fidelity check, the row round-trip under the `nl_NL` workbook, a sort and an undo, then deletes the month (`--keep` leaves it). It uses a scratch index, never the real one, and needs the OAuth token.

### Manual Testing

1. Start the bot: `venv/bin/python src/bot.py`
2. Use `/upload` with the anonymised fixture on a test setup (see "Testing Commands")
3. Check the progress lines and the summary in your thread, and `/status`
4. Interrupt a run (stop the bot mid-upload), restart, and `/resume`
5. `/cancel` an open run; `scripts/undo_upload.py <upload_id> --dry-run` a finished one

## Data Directory Structure

The bot uses a dedicated `data/` directory for runtime files, keeping source code separate from user data. It is not in git and must be in the backup set: `sheet_index.json` and the OAuth token cannot be rebuilt from anywhere else.

```txt
data/
├── google/
│   ├── oauth_client.json      # OAuth client (Desktop app)
│   └── authorized_user.json   # OAuth token from scripts/google_login.py
├── sheet_index.json           # Month -> spreadsheet id (authoritative)
├── period_state.json          # Period anchor and history
├── upload_ledger.json         # Dedup record and write audit
├── failed_uploads.json        # Failed sheet writes, for retry_failed_transactions.py
├── runs/                      # One JSON per upload run
│   └── {upload_id}.json
└── uploads/                   # Saved attachments, removed when the run closes
    └── {upload_id}/{n}-{filename}.csv (+ .normalised.csv)
```

### Path Configuration

All directory paths are configured in `src/config/config_settings.py`, relative to the project root:

```python
UPLOAD_DIR = "data/uploads"
RUNS_DIR = "data/runs"
SHEET_INDEX_PATH = "data/sheet_index.json"
UPLOAD_LEDGER_PATH = "data/upload_ledger.json"
PERIOD_STATE_PATH = "data/period_state.json"
GOOGLE_OAUTH_TOKEN_PATH = "data/google/authorized_user.json"
```

`finance_core.config_access.project_path` turns them into absolute paths from the project root, so behaviour does not depend on the working directory when the bot is started.

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

Category names are what the user sees in the sheet, and the `Summary` tab sums by label: a new category also needs its label in the category table of the template and of any existing month it should appear in.

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

   A rule that needs a condition goes in `CONDITIONAL_RULES_EXPENSE` / `CONDITIONAL_RULES_INCOME` as `(pattern, condition, (template, category))`, with the condition in `rule_conditions.py` syntax.

3. Rules that name people or amounts belong in the git-ignored `src/config/local_rules.tsv` instead (format in `finance_core/local_rules.py`), usually written by `scripts/apply_rule_draft.py` from an evaluation draft.

### Adding New Commands

1. Add to `src/bot_commands.py`:

   ```python
   @app_commands.command(name="newcommand", description="Description")
   async def new_command(self, interaction: discord.Interaction):
       await interaction.response.send_message("Hello!")
   ```

2. Start it with `if not await self._allowed(interaction): return`, so only the household can use it
3. Keep Discord out of `finance_core`: put the logic in `export.Pipeline` or a module, and let the command format the reply
4. Add a test to `tests/test_bot_commands.py`; one test there loads the cog into a real command tree and checks Discord's name and description limits
5. Update the command tables in `AGENTS.md` and `README.md`

## Deployment

### Production Checklist

- [ ] Configuration set correctly in `src/config/config_settings.py` (the self-check passes)
- [ ] Discord bot token secured
- [ ] OAuth token and client in `data/google/`, mode 0600
- [ ] `data/sheet_index.json` lists every month (`/months list`)
- [ ] `data/` in the backup set
- [ ] Proper file permissions
- [ ] Log rotation configured

### Configuration

All configuration is managed in `src/config/config_settings.py`; see `config_settings.example.py` for every key with its default and `AGENTS.md` for what each group does:

```python
# Required
DISCORD_TOKEN = "your_production_token"
MENTION_USER_IDS = [123456789012345678]      # the household

# Optional settings
REMINDER_CHANNEL_ID = channel_id              # reminders and progress threads
DAILY_REMINDER_TIME = "09:00"
CSV_DOWNLOAD_LINK = "https://your-bank.com/export"
```

The bot also respects the `TZ` environment variable for timezone configuration.

### Running in Production

Production runs in Docker on the Pi through `./run.sh` (`--force-rebuild` for a clean build). It refuses to deploy without `src/config/config_settings.py`, a real Discord token or `data/google/authorized_user.json`. `data/` and `src/config` are bind-mounted (the config read-only), so a change to the config or the local rules needs `docker restart finance-automation-bot`, not a rebuild. `--force-rebuild` prunes Docker, which can remove the image that is running now: `docker tag` it first to keep a rollback.

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

4. **`config: ... is missing ...` at startup**
   - The config predates a change; copy the named keys from `config_settings.example.py`

5. **"Google authorisation failed" in a run**
   - The OAuth token was revoked or expired; run `scripts/google_login.py` on the workstation, copy the token to `data/google/`, then `/resume`

6. **An upload is refused**
   - "still appending": a previous run's write did not finish; `/resume` that run first
   - a suspicious split: the summary gives the reason and nothing was written; if the anchor is wrong, `scripts/seed_state.py --set-anchor`; if the split is right and the check is forceable, repeat with `force`

7. **A month fails with "no sheet for MM/YYYY"**
   - The month is not in the index and is not the month after the newest indexed one, so the bot will not create it. Register the existing sheet with `/months register`, then `/resume`

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
