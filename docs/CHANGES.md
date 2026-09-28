# Bot.py Update Summary

## Recent Changes

### Multi-Month Upload (2026-09-27; release follow-up 2026-09-28)

Design and work log: `docs/plans/MULTI_MONTH_UPLOAD_PLAN.md`.

**What users notice**:
- One `/upload` takes up to five ASN exports and may cover several financial months. The rows are split on DUO / Anamata salary income: a month starts on that income's date, and a boundary on the 15th or later names the next calendar month.
- Each financial month is its own spreadsheet, `Maandelijks Budget MM/YYYY`. The next month is created automatically from the template and moved into the `Financiën` folder, with the previous month's closing balance as its starting balance (`Summary!L8`) when that month is known; otherwise the summary asks you to fill it in. The bot only creates the month after the newest one it knows.
- No review buttons any more: every row is written at upload time. A row the AI was unsure about (below `AI_CONFIDENCE_THRESHOLD`, 0.75) or could not answer gets the category `! Nog in te delen !`; a row a rule marks for checking keeps its category and gets `? ` before its description. The sheet is where these are checked and fixed.
- Progress lines and a summary go to your private `Approvals-<name>` thread in the reminder channel: months written, sheets created, rows skipped as already uploaded, flagged and marked counts, and per flagged row the AI guess that was not used (beyond 40 rows as an attached `.txt`).
- Uploading an overlapping export does not write rows twice: rows already written are skipped and counted.
- An interrupted run keeps its state: `/status` shows what is not written, `/resume` finishes it, `/cancel` abandons it.
- `/months list` shows which sheet holds which month; `/months register` adds a sheet the bot did not create.
- `/review`, `/cached`, `/pending` and `/resetsheet` are removed, and with them the pending approval queue, cached transactions and per-user sessions. Every command is limited to the household (`MENTION_USER_IDS`).
- `/sort` takes an optional month; by default it sorts every sheet the last run touched.
- `/upload` accepts an optional note as AI context for that upload and any resume; it does not force a category.
- New rows carry a note on the description cell with bank details. A flagged row includes the unused AI guess when available. Sorting and undo keep notes aligned with rows.

**How it works**:
- Rows are appended below what is there; a sheet is never cleared and rewritten. An upload ledger (`data/upload_ledger.json`) records every row before it is written (dedup) and after (the audit that `undo_upload.py` uses).
- Categorisation: conditional rules and the rule tables in `constants.py`, then the household's own rules in `src/config/local_rules.tsv` (git-ignored), then Claude (Sonnet, via the Claude Code CLI) in batches, several chunks in parallel. Transfers from the savings account that match a purchase are passed to the AI as a hint, never as a category.
- Google access is the user's own account through OAuth (scopes `spreadsheets` and `drive.file` only). The service account is kept only for read-only inspection scripts.
- Created months rebind the Transactions dropdowns after both tabs exist and retain the first data row's date and currency formats. The synthetic live sandbox passed creation, round trips, sorting and undo on 2026-09-28. The owner approved its dropdowns and notes; both synthetic sandbox sheets were then trashed.

**Configuration**:
- Added: `GOOGLE_OAUTH_CLIENT_PATH`, `GOOGLE_OAUTH_TOKEN_PATH`, `GSHEET_NAME_PATTERN`, `GSHEET_TEMPLATE_ID`, `GSHEET_FOLDER_ID`, `GSHEET_AUTO_CREATE`, `GSHEET_CREATE_NONADJACENT`, `GSHEET_DATA_START_ROW`, `SHEET_INDEX_PATH`, `UPLOAD_LEDGER_PATH`, `PERIOD_STATE_PATH`, `RUNS_DIR`, `PERIOD_BOUNDARY_MARKERS`, `PERIOD_BOUNDARY_MIN_AMOUNT`, `PERIOD_MIN_DAYS`, `PERIOD_MAX_DAYS`, `PERIOD_STEP_DAYS`, `PERIOD_LABEL_SPLIT_DAY`, `AI_CONFIDENCE_THRESHOLD`, `AI_PER_TX_FALLBACK_LIMIT`, `AI_MAX_PARALLEL_CHUNKS`, `AI_RUN_MAX_MINUTES`, `AI_BUDGET_TRIP_ACTION`, `SUMMARY_FLAGGED_LINES`, `ACCOUNT_ROLES`, `LOCAL_RULES_PATH`.
- Retired: `GSHEET_TAB`, `GSHEET_EXPENSE_START_ROW`, `GSHEET_INCOME_START_ROW`, `APPROVAL_CHANNEL_ID`, `APPROVAL_WEBHOOK_URL`, `PENDING_APPROVALS_FILE`, `SESSION_DIR`, `CLAUDE_MODEL`, and after the cutover `GOOGLE_AUTH_MODE`, `GSHEET_NAME`, `GOOGLE_CREDENTIALS_PATH`. The service-account mode and the single-sheet `GoogleSheetsExporter` are gone.
- The bot checks its config at startup and stops with one line naming any missing key (`src/config_check.py`).

**New scripts**:
- `google_login.py` (OAuth token, once), `register_sheets.py` (the month index), `seed_state.py` (period anchor and ledger from the sheets), `undo_upload.py` (reverse one run).
- `retry_failed_transactions.py` rewritten for the new layer; it takes no user id any more and skips rows a still-open run owes.
- `eval_categoriser.py`, `rule_coverage.py`, `apply_rule_draft.py` (score the categoriser against hand-checked months and turn rule decisions into the local rules file; counts only), `sheet_shape.py` (`--summary`, `--folder`), `make_fixture.py`, `sandbox_check.py`, `time_ai_chunk.py`, `add_income_placeholder.py` (one-off).
- `repair_months.py` checks and repairs the known 2026 layout defects; its live repair was completed and visually approved on 2026-09-28. `backfill_notes.py` backfilled 454 unambiguous description notes on 06-10/2026 after a counts-only dry run; 29 ambiguous rows were left untouched.
- Removed: `recategorize_pending.py`.

**Deployment**:
- `run.sh` refuses to deploy without `data/google/authorized_user.json` and no longer checks for the service-account key.
- `src/config` is bind-mounted read-only: a config or local-rules change needs a restart, not a rebuild.
- `--force-rebuild` prunes Docker and can remove the image now running; `docker tag` it first to keep a rollback. `data/` is a bind mount and survives.
- `data/` must be in the backup set: `data/sheet_index.json` is the only record of which sheet holds which month, and the OAuth token lives in `data/google/`.
- The template and the 2026 months carry `! Nog in te delen !` in the income table (`Summary!H35`), so flagged income counts in the totals.

### Discord Approval UI - Session 3 (2025-12-17)

**Proactive Discord Approval Flow**:
- Low-confidence transactions sent to private thread (`Approvals-{username}`) for approval
- Single "Start Review" button launches familiar ephemeral 1-by-1 transaction flow
- AI suggestions work like regex matches: pre-selected category, pre-filled description
- Persistent buttons work even after bot restart

**New Files**:
- `src/finance_core/pending_transactions.py` - Manages approval queue with JSON persistence
- `src/automation/discord_notifier.py` - Private threads and PendingReviewView

**Configuration**:
- Added `APPROVAL_CHANNEL_ID` to `config_settings.py` - Set to your approval channel
- Added `PENDING_APPROVALS_FILE` for queue persistence

**How It Works**:
1. Upload CSV via `/upload` command
2. High-confidence transactions (regex + AI ≥75%) upload automatically
3. Low-confidence transactions queued and notification sent to private thread
4. User clicks "Start Review" to launch ephemeral transaction-by-transaction flow
5. Each transaction shows AI suggestion with confidence %, user confirms/edits/skips
6. Approved transactions upload to Google Sheets

### Auto-Upload Fix & Sorting Feature (2025-12-17)

**Auto-Categorized Transaction Upload Fix**:
- Fixed issue where auto-categorized transactions weren't uploading immediately
- High-confidence transactions (regex + AI ≥75%) now upload to Google Sheets right away
- Manual review transactions stored separately in session
- Only manual-review transactions remain for user interaction

**Chronological Sorting**:
- Added `sort_transactions_by_date()` method to GoogleSheetsExporter
- Uses Python date parsing for proper DD-MM-YYYY chronological order (not lexicographic)
- Auto-sorts sheet after batch uploads complete
- New `/sort` slash command for manual sorting

**New Regex Patterns**:
- Boodschappen: Odin, Lakerveld, Ararat, Vigola (consolidated patterns)
- Goeie Doelen: Specific charity names (KiKa, World Vision, Rode Kruis, etc.)
- Income: zorgkostennota (health insurance refunds)

**New Commands**:
- `/sort` - Manually trigger chronological sorting of Google Sheets

### AI Categorization & Auto-Upload (2025-12-16)

- Integrated Claude 3.5 Haiku for AI-powered transaction categorization
- Two-tier categorization: regex rules (100% confidence) → AI (0-100% confidence)
- Auto-upload for high-confidence transactions (≥75%)
- `/review` command to inspect auto-categorizations
- Async Claude CLI integration for Docker deployments

### Data Directory Restructuring

- **Created Unified Data Directory**: Moved runtime data from mixed locations to `data/` directory
- **Session Management Cleanup**: Moved sessions from `/sessions` and `/src/sessions` to `data/sessions/`
- **Upload Organization**: Moved uploads from hardcoded paths to `data/uploads/`
- **Path Independence**: Bot now works consistently regardless of working directory
- **Configuration Centralization**: All directory paths now configurable in `config_settings.py`
- **Documentation Updates**: Updated README.md and DEVELOPMENT.md with new structure

### Benefits

- Clean separation of source code and runtime data
- Consistent path resolution from any working directory
- Better project organization following Python best practices
- Easier deployment and backup strategies

## Previous Changes

### 1. **Modernized Bot Architecture**

- **Updated to Discord.py 2.x**: Changed from legacy message commands to modern slash commands
- **Added Extension Loading**: Bot now loads `bot_commands.py` as a cog extension
- **Better Error Handling**: Added comprehensive error handling for commands and tasks
- **Improved Logging**: Added status messages and error reporting

### 2. **Fixed Import Issues**

- **Resolved Config Conflicts**: Renamed `config.py` to `config_settings.py` to avoid conflict with `config/` directory
- **Added Missing Modules**: Created `__init__.py` files for all packages
- **Updated Import Statements**: Fixed all import paths to work with the new structure

### 3. **Enhanced Configuration**

- **Environment Variable Support**: Added `.env` file support with python-dotenv
- **Flexible Configuration**: Settings can be set via environment variables or config file
- **Better Defaults**: Improved default values and validation

### 4. **Updated Command Structure**

- **Slash Commands**: All commands now use modern Discord slash command syntax
- **Better UX**: Improved user messages with emojis and clearer feedback
- **Error Recovery**: Added proper error handling and user feedback

### 5. **Compatibility Layer**

- **Dual Support**: Updated `process_csv_file()` to work with both old Context and new Interaction objects
- **Backward Compatibility**: Legacy functionality preserved while adding modern features

## New File Structure

```txt
src/
├── bot.py                     # ✅ Updated - Modern bot with extension loading
├── bot_commands.py            # ✅ Updated - Enhanced slash commands
├── config_settings.py         # ✅ New - Centralized configuration
├── constants.py               # ✅ Existing - Categories and rules
├── asnexport.py              # ✅ Existing - Legacy processing
├── finance_core/
│   ├── __init__.py           # ✅ New - Package initialization
│   ├── csv_helper.py         # ✅ Existing - CSV processing
│   ├── export.py             # ✅ Updated - Dual compatibility
│   ├── session_management.py # ✅ Existing - Session handling
│   └── ui/
│       ├── __init__.py       # ✅ New - Package initialization
│       └── transaction_prompt.py # ✅ Existing - UI components
└── config/
    ├── __init__.py           # ✅ New - Package initialization
    ├── config.json           # ✅ Existing - JSON config
    ├── google_service_account.json # ✅ Existing - Google credentials
    └── spaarpot_uuid_map.py  # ✅ Existing - UUID mapping
```

## Key Features Now Working

### ✅ **Modern Discord Commands**

```txt
/upload    - Upload CSV files with drag & drop
/resume    - Resume interrupted sessions  
/status    - Check processing progress
/cancel    - Clear current session
```

### ✅ **Daily Reminders**

- Configurable time (default 09:00)
- User mention support
- Channel targeting
- Error resilience

### ✅ **Session Management**

- Persistent sessions across bot restarts
- User-specific file handling
- Progress tracking
- Error recovery

### ✅ **Enhanced Error Handling**

- Import validation
- Runtime error recovery
- User-friendly error messages
- Automatic cleanup

## Next Steps

### 1. **Configuration**

```bash
# Copy environment template
cp .env.example .env

# Edit .env file
DISCORD_TOKEN=your_bot_token_here
REMINDER_CHANNEL_ID=your_channel_id
```

### 2. **Add User IDs**

Edit `config_settings.py`:

```python
MENTION_USER_IDS: List[int] = [
    123456789012345678,  # Your Discord user ID
    987654321098765432,  # Other user IDs
]
```

### 3. **Run the Bot**

```bash
cd src
source ../venv/bin/activate  # If using virtual environment
python bot.py
```

## Testing

All imports and basic functionality tested and working:

- ✅ Configuration loading
- ✅ Discord.py integration  
- ✅ Extension loading
- ✅ Finance core modules
- ✅ Session management
- ✅ CSV processing

The bot is now ready for production use with your existing transaction processing workflow!
