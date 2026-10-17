# Ingest notes

Notes on the headless `finance` command line (`src/cli.py`) against the spec
`~/Coding/specs/finance-ingest.md`. Only `age` exists today; `ingest` (spec P2)
is a stub that exits 1.

## Amendment 5a: where `finance age` reads from until P2 ingest exists

Spec Decision 5 computes the backlog age from `data/ingest-log.json` and the
review queue. Neither exists: P2 ingest never ran, so there is no ingest log,
and the Discord review queue was removed with the multi-month upload (rows the
bot is unsure about are written flagged and checked in the sheet). Until P2
ingest writes `ingest-log.json`, `age` reads the run files instead. The output
contract does not change:

```
src/cli.py age --json
{"days_since_last_statement": <int|null>, "pending_review_rows": <int|null>}
```

One line, these two keys in this order, exit 0 in every data state (fresh,
stale, no runs, unreadable). Staleness is the signal, never the exit code.

**Newest statement.** The newest run file `RUNS_DIR/<upload_id>.json` (default
`data/runs/`, read through `finance_core.run_state.RunStore`) with
`closed == "complete"`, ordered by `closed_at`, leaving out a run whose ledger
entry (`Ledger.from_settings().run(upload_id)`, `data/upload_ledger.json`) has
`undone_at` set. The upload pipeline (`export.Pipeline.process_upload`) writes
these files and keeps them after the run closes. Open, `abandoned` and
`refused` runs are not a statement.

**`days_since_last_statement`.** The Europe/Amsterdam calendar date of now
minus the Europe/Amsterdam calendar date of that run's `closed_at`. A
`closed_at` without an offset is read as UTC; a negative result (clock skew) is
0. `null` when no run qualifies. The timezone is fixed, not the bot's
`TIMEZONE` setting, so `age` needs no config.

**`pending_review_rows`.** The sum, over open runs (`closed` is null), of
`counts.rows` (or `len(rows.expenses) + len(rows.income)`) for every period
whose status is not `written`: the accepted rows that only `/resume` can still
write. `0` when the runs directory is missing. Flagged rows already in the
sheet are not counted, because that needs a Google read.

**Unreadable state.** If a run file or the ledger cannot be read, both values
are `null` and stderr gets one line, `finance age: unreadable run state`, with
no path and no traceback. Exit code 0.

**Sources rejected.** `data/uploads/` is deleted when a run closes;
`data/bank_downloads/` belongs to the abandoned scraper; booking dates would
mean reading transaction rows.

When P2 ingest exists, the ingest log replaces the run files as the source of
`days_since_last_statement`; the keys, types and exit behaviour stay the same.

## Running it

```bash
src/cli.py age --json          # or through a symlink, e.g. ~/bin/finance
src/cli.py age                 # one plain line, counts and a date only
```

System `python3`, stdlib and `finance_core` only: no venv, no Docker, no
`src/config/config_settings.py` (when the config exists, `RUNS_DIR` and
`UPLOAD_LEDGER_PATH` are taken from it). Importing `cli` loads neither
`discord` nor any `google*` module. `--runs-dir` and `--ledger` point it at
other files, as the tests do. The user that runs it must be able to read
`data/runs/` and `data/upload_ledger.json`.

## Wiring contract

rp5's weekly digest runs `src/cli.py age --json` and embeds the result under key `finance`; the vps runner never calls rp5.

The consumer is `collect_finance()` in `~/.claude-config/bin/personal-digest`,
which runs `<DIGEST_FINANCE_BIN> age --json` and parses stdout; stderr is not
part of the contract.
