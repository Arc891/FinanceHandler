# Discord Finance Automation Bot

A Discord bot for a household's monthly budget. Upload one or more ASN Bank CSV
exports with `/upload`; the bot splits them into financial months, categorises
every transaction (rules first, then Claude), and appends the rows to one Google
spreadsheet per month, creating the next month's sheet from a template when it is
missing.

There is no review step in Discord. Rows the bot is unsure about are written
anyway, with the category `! Nog in te delen !` or a `? ` before the description,
and the sheet is where you check them. An interrupted upload keeps its state and
can be continued with `/resume`.

Agent and developer detail (architecture, state files, recovery scripts) is in
[AGENTS.md](AGENTS.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## How a month is processed

1. `/upload` with up to five CSV exports. The command answers at once; progress
   and the summary appear in your private `Approvals-<name>` thread.
2. Rows present in several exports, or already written by an earlier upload, are
   skipped.
3. The rows are split into financial months. A month starts on the DUO or salary
   income; one that arrives on day 15 or later names the next calendar month
   (DUO on 24-03-2026 opens `04/2026`). A split that looks wrong writes nothing
   unless you pass `force`.
4. Each month's rows are categorised and appended below the rows already in its
   sheet, which is then sorted by date.
5. The summary lists the months, any sheets created, skipped rows, and the
   flagged rows with the AI guess that was not used.

## Commands

All commands are limited to the household (`MENTION_USER_IDS`).

| Command | Does |
|---|---|
| `/upload attachment [attachment2..5] [force]` | Process up to five ASN CSV exports |
| `/resume [upload_id]` | Continue an unfinished run (newest by default) |
| `/status` | Open runs, and per month what is not written yet |
| `/cancel [upload_id] [confirm]` | Abandon an open run; never undoes a write |
| `/sort [month]` | Sort one month (`MM/YYYY`) or every sheet the last run touched |
| `/months list` | Which spreadsheet belongs to which month |
| `/months register label url [force]` | Add a month sheet the bot did not create |

A daily reminder to upload is posted in `REMINDER_CHANNEL_ID` at
`DAILY_REMINDER_TIME`.

## Checking the sheet

Each month is a spreadsheet named `Maandelijks Budget MM/YYYY` with two tabs:

- **Transactions**: expenses in columns B-E, income in G-J (date, amount,
  description, category), data from row 5.
- **Summary**: totals per category, starting balance in `L8`, closing balance in
  `E17`. The starting balance of a created month is the previous month's closing
  balance.

After an upload, filter the Transactions tab on:

- category `! Nog in te delen !`: the bot did not know, or the AI was not sure
  enough. These amounts are still counted in the Summary under that category.
- descriptions starting with `? `: a household rule chose the category but asked
  for a check.

## Setup

### Prerequisites

- Python 3.12
- A Discord bot token (Developer Portal, with the Message Content and Server
  Members intents)
- A Google Cloud OAuth client (desktop app) with the Sheets and Drive APIs enabled
- The Claude Code CLI (`claude`) logged in, for AI categorisation. Without it the
  bot runs on rules only and flags the rest.

### Install

```bash
scripts/setup.sh          # venv, dependencies, config copy

# or by hand
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp src/config/config_settings.example.py src/config/config_settings.py
```

Fill in `src/config/config_settings.py`. The example file is the reference for
every key and its default; the bot refuses to start and names the keys that are
missing.

### Google access

The bot writes as your own Google account. Create the token once, on the
workstation, in your own terminal:

```bash
venv/bin/python scripts/google_login.py
```

It asks for exactly two scopes, `spreadsheets` and `drive.file`, and stores the
token in `data/google/authorized_user.json` (the OAuth client goes in
`data/google/oauth_client.json`). The script's docstring covers the browser steps.

Then tell the bot which spreadsheet belongs to which month, either with
`/months register` from Discord or with `scripts/register_sheets.py`, and seed the
period anchor and the dedup record from those sheets:

```bash
venv/bin/python scripts/register_sheets.py list
venv/bin/python scripts/seed_state.py
```

`data/sheet_index.json` is the only record of which sheet is which month (the bot
cannot search Drive), so back up `data/`.

### Run

```bash
python src/bot.py         # locally

./run.sh                  # Docker, as deployed on the Pi
```

`run.sh` checks for the config, a real Discord token and the Google token before
it deploys, and mounts `data/` and `src/config` from the host, so a config change
needs only `docker restart finance-automation-bot`. `./run.sh --force-rebuild`
prunes Docker; tag the running image first if you want a rollback.

### Tests

```bash
venv/bin/python -m pytest -q
```

The tests use fakes and an anonymised fixture; they never call Google.

## Categories and rules

Categorisation runs in this order:

1. Conditional rules and rule tables in `src/constants.py` (merchant patterns).
2. Household rules in `src/config/local_rules.tsv` (not in git: names and
   amounts), one tab-separated rule per line; the format is described in
   `src/finance_core/local_rules.py`.
3. Claude, for everything no rule decides. Answers below
   `AI_CONFIDENCE_THRESHOLD` (0.75) are written as `! Nog in te delen !`.

A new category must also be added to the Summary tab of the template and of the
existing months, because the Summary sums by category name. See "Adding
Categories" in [AGENTS.md](AGENTS.md).

## CSV format

ASN Bank export with the columns Date, Account IBAN, Counterparty IBAN,
Counterparty Name, Transaction Amount, Currency, Transaction Code and Remittance
Information. The uploaded file is never changed.

## When something goes wrong

- A run stopped halfway: `/status`, then `/resume`. A write that failed is
  checked against the sheet before anything is appended again.
- Rows that could not be written are kept in `data/failed_uploads.json`:
  `scripts/retry_failed_transactions.py --dry-run`, then without `--dry-run`.
- To take a whole upload back out of the sheets:
  `scripts/undo_upload.py <upload_id> --dry-run`, then without `--dry-run`.

## Security

- Never commit `src/config/config_settings.py`, `src/config/local_rules.tsv` or
  anything under `data/`.
- The bot logs labels and counts only, never names, descriptions or amounts.
- Do not add Google Drive scopes beyond `drive.file`: the others are restricted
  and need a paid security assessment.

## Changelog

See [docs/CHANGES.md](docs/CHANGES.md).
