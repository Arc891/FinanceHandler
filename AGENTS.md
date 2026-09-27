# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Project Overview

This is a Discord bot that automates personal finance management. It reads ASN Bank CSV exports uploaded through a Discord slash command, splits them into financial months, categorises every transaction (rules first, then Claude), and appends the rows to one Google spreadsheet per financial month. There is no review step in Discord: rows the bot is unsure about are written flagged, and the sheet is where the user checks them. Run state is persisted, so an interrupted upload can be resumed.

## Who uses this

The owner and their partner, through Discord slash commands, once a month with an ASN
Bank CSV. The Google Sheet is the record. What matters: every transaction lands exactly
once in the right category, nothing is dropped silently, and the monthly run takes few
prompts. Sheet layout and category names are end-user behaviour, and rewriting rows
already in the sheet counts as changing stored data.

## Running & Development Commands

### Starting the Bot

```bash
# From project root
python src/bot.py

# Or from src directory
cd src
python bot.py
```

### Starting the Automation API (New - Session 1+)

```bash
# Start FastAPI server for n8n integration
cd src
python -m api.automation_endpoints

# Runs on http://localhost:8000
# Requires X-API-Key header for authentication
```

### Testing Bank Scraper

```bash
# Direct test (useful for debugging)
cd src
python -m automation.bank_scraper

# Via API (more realistic)
curl -X POST http://localhost:8000/api/check-session \
  -H "X-API-Key: change-me-in-production"
```

### Setup & Installation

```bash
# Quick setup (runs venv creation, pip install, and config copy)
scripts/setup.sh

# Manual setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp src/config/config_settings.example.py src/config/config_settings.py

# Google access, once, on the workstation, in your own terminal (see "Google access")
venv/bin/python scripts/google_login.py
```

`bot.py` runs `config_check.check_required_settings()` before anything else: a config that lacks a required key stops the bot with one line naming the missing keys.

### Tests

```bash
venv/bin/python -m pytest -q
```

`pytest.ini` sets `testpaths = tests`, `pythonpath = src scripts` and `asyncio_mode = auto`. Tests use fakes (`tests/fakes.py`, `tests/pipeline_env.py`) and the anonymised fixture `tests/fixtures/multi_month.csv`; they do not call Google.

### Deployment

```bash
# Docker deployment
./run.sh

# Force rebuild Docker image
./run.sh --force-rebuild
```

`run.sh` refuses to deploy without `src/config/config_settings.py`, a real `DISCORD_TOKEN` in it, or the OAuth token `data/google/authorized_user.json`; it does not check for a service-account key. It bind-mounts `data/` and `src/config` (read-only), so a config or local-rules change needs a restart (`docker restart finance-automation-bot`), not a rebuild. `--force-rebuild` runs `docker system prune -f --volumes`: `data/` survives (it is a bind mount), but the image now running may not, so `docker tag` it first to keep a rollback.

### Utilities

All scripts run from the project root with `venv/bin/python scripts/<name>.py`; each one's docstring is its manual.

| Script | Does |
|---|---|
| `google_login.py` | Creates the OAuth token (once, workstation) |
| `register_sheets.py` | `seed` / `add` / `paste` / `list` on `data/sheet_index.json` |
| `seed_state.py` | Seeds the period anchor and the weak ledger from the indexed sheets; `--set-anchor DD-MM-YYYY MM/YYYY`; writes only after you type `yes` |
| `retry_failed_transactions.py` | Re-appends rows from `data/failed_uploads.json`; `--dry-run`; skips entries whose run is still open |
| `undo_upload.py <upload_id>` | Removes one run's rows from its write audit and restores the anchor; `--dry-run`, `--drop-created` |
| `sheet_shape.py` | Structure-only report of sheets (`--summary`, `--folder ID`) or CSVs; service account via `--credentials` |
| `eval_categoriser.py` | Scores the categoriser against hand-checked months; counts only (see "Evaluation") |
| `rule_coverage.py`, `apply_rule_draft.py` | Rule analysis for the eval, and turning the decided draft into `src/config/local_rules.tsv` |
| `make_fixture.py` | Anonymises a real export into a test fixture |
| `add_income_placeholder.py` | One-off, done: wrote `! Nog in te delen !` into `Summary!H35` of the template and the 2026 months |
| `sandbox_check.py`, `time_ai_chunk.py` | Live Google check on a synthetic month; AI chunk timing |

## Architecture Overview

### Core Data Flow

1. **Upload**: `/upload` takes up to five CSV attachments (plus `force`). They are saved under `data/uploads/<upload_id>/`, the command answers at once, and the run continues as a background task (`export.Pipeline.process_upload`).
2. **Parse**: `csv_helper.py` loads each export; rows with an unparsable date are dropped and reported.
3. **Dedup**: rows present in several attachments collapse to one (`ledger.collapse_within_upload`); rows already written by an earlier upload are skipped (`ledger.filter_new`).
4. **Split**: `periods.py` splits the rows into financial months on DUO / Anamata salary income, using the persisted anchor (`period_state.py`). A suspicious split writes nothing unless `force`.
5. **Resolve**: per month, `sheet_registry.py` finds the spreadsheet in `data/sheet_index.json`, or creates the next month from the template.
6. **Categorise**: rules, then the AI in batch (`categorization_engine.py`). Every row gets a category; unsure ones are flagged (see "Categorisation").
7. **Append**: `sheet_writer.commit_append` appends each block below the rows already there; the ledger records the rows before the write and audits them after it.
8. **Sort**: every touched sheet is sorted by date once, except a sheet whose write did not finish.
9. **Summary**: progress lines and a summary (months, created sheets, skips, flagged rows with the AI guess that was not used) go to the user's Discord thread.

There is no second phase: when a run completes, every accepted row is in a sheet.

### Directory Structure

```
/
├── AGENTS.md / CLAUDE.md       # Agent instructions (CLAUDE.md includes AGENTS.md)
├── README.md
├── run.sh, Dockerfile          # Docker deployment
├── pytest.ini, requirements*.txt
├── docs/
│   ├── CHANGES.md, DEVELOPMENT.md
│   ├── plans/MULTI_MONTH_UPLOAD_PLAN.md   # Design and work log of the multi-month upload
│   ├── automation/             # Bank automation and AI categorisation docs
│   └── archive/
├── scripts/                    # Tools (table above); browsercode/ for bank automation setup
├── src/
│   ├── bot.py                  # Entry point: config self-check, cog loading, daily reminder
│   ├── bot_commands.py         # Discord slash commands (FinanceBot cog)
│   ├── config_check.py         # REQUIRED_SETTINGS self-check
│   ├── constants.py            # Categories, rule tables, conditional rules
│   ├── config/                 # config_settings.py, local_rules.tsv, service-account key (NOT in git)
│   ├── api/automation_endpoints.py   # FastAPI for n8n
│   ├── automation/             # ai_categorizer, claude_provider, data_anonymizer, bank_scraper
│   └── finance_core/
│       ├── export.py           # Pipeline: process_upload, resume, cancel, sort, status
│       ├── run_state.py        # data/runs/<upload_id>.json
│       ├── csv_helper.py       # CSV parsing
│       ├── periods.py, period_state.py   # Financial months and the anchor file
│       ├── sheet_index.py, sheet_registry.py   # Month -> spreadsheet index, create from template
│       ├── sheet_writer.py, row_tuple.py       # Append, read, compact, sort, remove
│       ├── ledger.py           # Dedup record and write audit
│       ├── google_auth.py, google_retry.py, google_sheets.py   # Credentials, bounded retry, row formatting
│       ├── categorization_engine.py, categorization_rules.py, local_rules.py,
│       │   rule_conditions.py, tx_features.py, pot_links.py    # Categorisation
│       ├── flagging.py         # What a result writes (placeholder, mark)
│       ├── discord_threads.py  # The user's progress thread
│       └── config_access.py    # setting(), project_path()
├── tests/                      # pytest; fixtures/multi_month.csv is anonymised
└── data/                       # Runtime data (NOT in git), see "State files"
```

### Key Architecture Patterns

**Financial months** (`periods.py`, pure): a month starts on the booking date of the first income matching `PERIOD_BOUNDARY_MARKERS` (DUO, Anamata) of at least `PERIOD_BOUNDARY_MIN_AMOUNT` in a new cycle. A boundary on day `PERIOD_LABEL_SPLIT_DAY` (15) or later names the next calendar month (DUO on 24-03-2026 opens `04/2026`). Rows before the first boundary in an upload belong to the anchor's month. The anchor and its history live in `data/period_state.json`.

**Sheet index** (`sheet_index.py`, `sheet_registry.py`): `data/sheet_index.json` maps `MM/YYYY` to a spreadsheet id and is authoritative. The bot has no Drive listing scope, so it cannot rebuild the index by searching; back it up with `data/`. `resolve` may create a month, `lookup` never does. A month is created only when the index misses, `GSHEET_AUTO_CREATE` is on, and the label is the month after the newest indexed one (adjacency guard; `GSHEET_CREATE_NONADJACENT` lifts it). A created month is copied from `GSHEET_TEMPLATE_ID`, named from `GSHEET_NAME_PATTERN`, moved into `GSHEET_FOLDER_ID`, passes a fidelity check (tabs, headers, validation, a behavioural totals check) before it enters the index, and gets the previous month's `Summary!E17` as its starting balance in `Summary!L8`.

**Append, never rewrite** (`sheet_writer.py`): the next free row is read from the sheet each time, never remembered. The writer appends and compacts; it never clears a sheet or writes above `GSHEET_DATA_START_ROW`. A values update is never retried: a failed write is reconciled on `/resume` against the baseline recorded before it. Comparisons go through `row_tuple.canonical`.

**Ledger** (`ledger.py`, `data/upload_ledger.json`): the dedup record is written before a block is appended (it may over-record, never under-record); the write audit is written after it, from what landed, and is what `undo_upload.py` removes. The strong key is date, amount, counterparty, raw remittance and the bank's sequence number. Rows written before the ledger existed are known by weak keys (date, absolute amount, block) that `seed_state.py` reads from the sheets.

**Run state** (`run_state.py`, `data/runs/<upload_id>.json`): holds the rows of every month not yet `written` and is saved after each status change (`split`, `resolved`, `categorised`, `appending`, `written`, `failed`). A month in `appending` only leaves it for `written`, through reconciliation. `/upload`, `/sort` and `undo_upload.py` refuse while any month is `appending`, and `/cancel` refuses for a run that has one. One run at a time (in-flight guard).

**Categorisation**: rules first, in order: `CONDITIONAL_RULES_*` in `constants.py` (a pattern plus a condition such as the sending account's role), the rule tables `CATEGORIZATION_RULES_*` in `constants.py` (`{c}` in a description template is the first capture group), then the household's local rules in `src/config/local_rules.tsv` (`local_rules.py`; conditions from `rule_conditions.py`, row features from `tx_features.py`, account roles from `ACCOUNT_ROLES`). A local rule may mark its row or hand it to the AI (`ai`). Rows no rule decides, and rows a local rule hands on, go to Claude through the Claude Code CLI (`claude -p`, Sonnet), anonymised, in batch chunks run in parallel (`AI_MAX_PARALLEL_CHUNKS`), one month per call; a failed chunk is retried once, then falls back to per-row calls up to `AI_PER_TX_FALLBACK_LIMIT`. `AI_RUN_MAX_MINUTES` bounds the AI time per `/upload` or `/resume`. Pot hints (`pot_links.py`: a purchase matching exactly one transfer in from the savings account within 7 days) are context in the AI prompt, never a category. If the CLI is unavailable the engine runs rules only.

**Flagging** (`flagging.py`): every row is written. A row whose AI answer is below `AI_CONFIDENCE_THRESHOLD`, or that got no answer (no rule, AI failed or budget spent), is written with the category `! Nog in te delen !` of its block; its AI description is kept when there is one, otherwise the bank text is used. The AI guess that was not used goes into the run state and the summary. A rule row marked for checking keeps its category and gets `? ` before its description. The summary counts `N flagged, M marked`. Both placeholders are withheld from the AI's category options.

**Household only**: every command is limited to `MENTION_USER_IDS`. Progress and summaries go to a private `Approvals-<name>` thread in the `REMINDER_CHANNEL_ID` channel (the name is historical).

**Log privacy**: log lines carry labels, statuses and counts, never a name, description, remittance text or amount (`tests/test_log_privacy.py`). An unexpected error in a run is posted to the thread by exception type only.

**Path resolution**: paths in the config are relative to the project root (`config_access.project_path`), so the bot works from any working directory.

## Configuration

All configuration lives in `src/config/config_settings.py` (copy from `config_settings.example.py`; the example is the reference for defaults). Required keys are listed in `src/config_check.py`.

- Discord: `DISCORD_TOKEN`, `DAILY_REMINDER_TIME`, `REMINDER_CHANNEL_ID` (reminders and progress threads), `MENTION_USER_IDS` (the household), `CSV_DOWNLOAD_LINK`, `TIMEZONE` (from `TZ`).
- Google: `GOOGLE_OAUTH_CLIENT_PATH`, `GOOGLE_OAUTH_TOKEN_PATH`, `GSHEET_NAME_PATTERN` (`"Maandelijks Budget {label}"`), `GSHEET_TEMPLATE_ID`, `GSHEET_FOLDER_ID`, `GSHEET_AUTO_CREATE`, `GSHEET_CREATE_NONADJACENT`, `GSHEET_DATA_START_ROW` (5).
- State files: `SHEET_INDEX_PATH`, `UPLOAD_LEDGER_PATH`, `PERIOD_STATE_PATH`, `RUNS_DIR`, `UPLOAD_DIR`; optional `FAILED_UPLOADS_PATH` (default `data/failed_uploads.json`).
- Periods: `PERIOD_BOUNDARY_MARKERS`, `PERIOD_BOUNDARY_MIN_AMOUNT`, `PERIOD_MIN_DAYS`, `PERIOD_MAX_DAYS`, `PERIOD_STEP_DAYS`, `PERIOD_LABEL_SPLIT_DAY`.
- AI: `AI_CONFIDENCE_THRESHOLD` (0.75; flag or not, never write or not), `AI_PER_TX_FALLBACK_LIMIT`, `AI_MAX_PARALLEL_CHUNKS`, `AI_RUN_MAX_MINUTES`, `AI_BUDGET_TRIP_ACTION` (`write_flagged`: the rest is written flagged; `stop`: later months wait for `/resume`), `SUMMARY_FLAGGED_LINES` (beyond it the flagged list is attached as a `.txt`).
- Rules: `ACCOUNT_ROLES` (`savings`, `partner_personal`, `user_personal` IBANs), `LOCAL_RULES_PATH`.
- Until the cutover's last step (plan Phase 4 step 6): `GOOGLE_AUTH_MODE` (`oauth`; still required by the self-check), `GSHEET_NAME`, `GOOGLE_CREDENTIALS_PATH`.
- Bank automation and API: `BANK_*`, `ASN_*`, `AUTO_DOWNLOAD_*`, `API_*`.
- Retired: `GSHEET_TAB`, `GSHEET_EXPENSE_START_ROW`, `GSHEET_INCOME_START_ROW`, `APPROVAL_CHANNEL_ID`, `APPROVAL_WEBHOOK_URL`, `PENDING_APPROVALS_FILE`, `SESSION_DIR`, `CLAUDE_MODEL`.

### Google access

The bot writes as the user's own Google account through an OAuth token made once with `scripts/google_login.py` (token in `data/google/authorized_user.json`, client in `data/google/oauth_client.json`). Scopes are exactly `spreadsheets` and `drive.file`; every other `drive.*` scope is restricted and needs a paid security assessment, so none may be added without the user's decision (`tests/test_google_auth.py` enforces it). The service account cannot create files (Drive quota 0) and is kept only for read-only inspection scripts (`sheet_shape.py`, `eval_categoriser.py`), which take it with `--credentials`.

### State files

| File | Role |
|---|---|
| `data/google/authorized_user.json` | OAuth token; remade with `google_login.py` |
| `data/sheet_index.json` | Authoritative month -> sheet index; back it up; `/months register` or `register_sheets.py` to repair |
| `data/period_state.json` | Anchor and history; rebuildable with `seed_state.py` |
| `data/upload_ledger.json` | Dedup record and write audit; weak part rebuildable with `seed_state.py` |
| `data/runs/` | Rows of unfinished runs; do not delete while a run is open |
| `data/uploads/<upload_id>/` | Saved attachments and their `.normalised.csv` copies; removed when the run closes |
| `data/failed_uploads.json` | Failed writes, for `retry_failed_transactions.py` |

## Adding Categories

Category names are end-user behaviour, and the sheet's `Summary` tab sums by label, so a new label must also be added to the category table of the template (and of existing months) or its rows are not counted. Edit `src/constants.py`:

```python
class ExpenseCategory(str, Enum):
    NEW_CATEGORY = ("Display Name", r"regex_pattern")

CATEGORIZATION_RULES_EXPENSE = {
    r"MERCHANT_PATTERN": ("{c} description", ExpenseCategory.NEW_CATEGORY),
}
```

The `{c}` placeholder in the description template gets replaced with the first capture group from the regex pattern. Rules that need a condition go in `CONDITIONAL_RULES_EXPENSE` / `CONDITIONAL_RULES_INCOME` as `(pattern, condition, (template, category))`, the condition in `rule_conditions.py` syntax (`role=partner_personal`, `amount>=100`, `code=BEA`, ...).

Household-specific rules (names, amounts) belong in the git-ignored `src/config/local_rules.tsv`, not in `constants.py`: one tab-separated line per rule, `direction pattern when category mark description [source]`, format in `local_rules.py`. A bad line stops the upload with its line number. The file is re-read when it changes. Do not open the real file: it holds personal names and amounts.

## CSV Format

Expected ASN Bank format with these columns:
- Date
- Account IBAN
- Counterparty IBAN
- Counterparty Name
- Transaction Amount
- Currency
- Transaction Code
- Remittance Information

The CSV parser normalizes this to an internal format with fields like `booking_date`, `creditor`, `debtor`, `transaction_amount`, `remittance_information`, plus `counterparty_iban`, `bank_sequence_no` (column 15) and `csv_row`.

**Note**: The uploaded file is never modified. Normalisation (e.g. replacing spaarpot UUIDs with names from `spaarpot_uuid_map.py`) writes a `<name>.normalised.csv` copy beside it, so code must iterate the run's `files` list, never glob `*.csv`.

## Google Sheets Layout

One spreadsheet per financial month, named `Maandelijks Budget MM/YYYY`, copied from the template, with two tabs:

- **Transactions**: headers in rows 1-4, data from row 5 (`GSHEET_DATA_START_ROW`). Expenses in columns B-E, income in G-J, each Date, Amount, Description, Category. Amounts are written as absolute values; the block gives the direction. Rows are appended, never rewritten, and the block is sorted by date after an upload.
- **Summary**: `SUMIF` totals per category over the Transactions tab, starting balance in `L8`, closing balance in `E17`. `! Nog in te delen !` is a category in both tables (`B45` expenses, `H35` income), so flagged amounts count in the totals.

## Bank Automation (New - Session 1+)

**Authentication Method**: Browsercode (5-digit PIN)

**Why Browsercode?**
- QR codes refresh every 4-5 seconds (impossible to automate)
- Browsercode = one-time setup, then fully automated
- No second device needed
- See `AUTOMATION_PLAN.md` for full details

**One-Time Setup** (must be done on automation server):
1. Run scraper with visible browser: `python -m automation.bank_scraper`
2. Navigate to ASN Bank login
3. Create browsercode (5 digits) when prompted
4. Verify with SMS/email codes
5. Session saved to `data/bank_session.json`
6. Server becomes "registered device"

**Browsercode Storage**:
```bash
# Store as environment variable (NEVER commit to git)
export ASN_BROWSERCODE="12345"

# Or in .env file
echo "ASN_BROWSERCODE=12345" >> .env
```

**After Setup**:
- Session persists across restarts (cookie-based)
- Downloads work automatically
- Browsercode only needed if session expires
- Can have max 10 registered devices per account

## Git Commit Rules

- **Never include self-references** in commit messages (no "Co-Authored-By: Claude", no "Generated with Claude Code", etc.)
- Keep commit messages concise and focused on what changed

## Important Implementation Notes

- The bot uses Discord.py's `commands.Bot` with slash commands via `app_commands`
- All slash commands are defined in `bot_commands.py` as the `FinanceBot` cog; `/months` is an `app_commands.Group` (`list`, `register`)
- Commands are synced on bot startup in `bot.py` `on_ready`
- `/upload` and `/resume` answer at once and run the pipeline as a background task: the interaction token dies after 15 minutes, a backlog run can take longer
- `export.py` has no Discord import: progress is an async callable taking one line, refusals raise `RunRefused` with the message to show
- Google calls are synchronous and may sleep in a retry, so the pipeline runs them in a worker thread (`asyncio.to_thread`)
- `google_retry.with_retry` wraps idempotent calls only (reads, create, copy); never a values update
- Summaries are split into embeds within Discord's 4,096 / 6,000 character caps
- Daily reminders use `@tasks.loop(minutes=1)` and check if current time matches configured time
- Logging uses colored output with unified format across all modules
- Discord.py library logging is reduced to WARNING level to minimize noise
- **Bank scraper** uses Playwright (Firefox) with persistent context for session management
- **API authentication** uses `X-API-Key` header (configured via `API_SECRET_KEY`)
- **Privacy when inspecting**: scripts that read real sheets or exports print structure and counts only, never descriptions, names, IBANs or amounts. Do not open `data/`, real CSV exports or `src/config/local_rules.tsv`; work from `tests/fixtures/multi_month.csv` or ask the user to run a script

## Evaluation

`scripts/eval_categoriser.py` runs old ASN exports through the real engine, one month per call, and scores the categories against hand-checked sheets (2024/2025 by default, `--years`; read-only, service account via `--credentials`). It prints counts, percentages and category names only; log messages are counted by kind, never shown. `--dry-run` matches without AI, `--rules` runs the rule pass alone (analysis in `rule_coverage.py`, decisions written by `apply_rule_draft.py`), `--local-rules` and `--account-roles` run the household's rules. Results and decisions are recorded in the plan, section 6.

## Failed Upload Recovery

A failed sheet write leaves an entry in `data/failed_uploads.json` (rows, `upload_id`, `period_label`, block). The same rows are also held by the run, so the first remedy is `/resume`, which reconciles the write against its recorded baseline.

```bash
venv/bin/python scripts/retry_failed_transactions.py --dry-run
venv/bin/python scripts/retry_failed_transactions.py
```

The script skips (and keeps) every entry whose run is still open, opens the month through the index (never creates one), skips rows the block already holds, appends the rest and audits them under the entry's `upload_id`. It does not sort: run `/sort` for the months it names. Run it while no upload is in progress.

To reverse a whole run: `scripts/undo_upload.py <upload_id>` (after `/resume` if a month is still `appending`).

## Discord Commands

All commands are limited to `MENTION_USER_IDS`.

| Command | Description |
|---------|-------------|
| `/upload attachment [attachment2..5] [force]` | Upload up to five ASN CSV exports; they are split into months and written; progress and summary in your thread |
| `/resume [upload_id]` | Continue an unfinished run (newest open run by default); never re-splits |
| `/status` | Every open run, and per month what is not written yet |
| `/cancel [upload_id] [confirm]` | Abandon an open run; `confirm` is needed when unwritten rows would be discarded; never undoes a write |
| `/sort [month]` | Sort sheets by date: the given `MM/YYYY`, or every sheet the last run touched |
| `/months list` | The month -> sheet index |
| `/months register label url [force]` | Add a sheet the bot did not create; `force` re-points a registered label or sheet |

Removed: `/review`, `/cached`, `/pending`, `/resetsheet`. The sheet is the review surface: filter on `! Nog in te delen !` and descriptions starting with `? `.
