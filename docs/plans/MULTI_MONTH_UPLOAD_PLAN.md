# Multi-month upload: plan

**Created**: 2026-09-20
**Revision**: 11 (after 9 scrutiny rounds including a cold read)
**Status**: **Reviewed. APPROVE WITH CONCERNS at round 9; loop closed by user decision.** Ready for Phase 0.
**Base**: `feature/browsercode-authentication` at `ef0c95c` (local = Pi = origin).
Work happens on a new branch `feat/multi-month-upload`; the Pi stays on the
current branch until Phase 4, because the tree is not runnable between phases.

> **What changed in revision 4.** Three decisions taken with the user on
> 2026-09-21 reshape the plan: (a) every transaction is written to its sheet at
> upload time and uncertain ones are flagged in the sheet with the existing
> `! Nog in te delen !` category — **the Discord review UI is removed
> entirely**; (b) an income placeholder category is added to the template and
> the existing 2026 months; (c) months are resolved through an explicit index.
> The removal of the review surface deletes about 3,300 lines and dissolves
> round 2's findings J6 and J7 and round 1's M2 outright.
>
> **What changed in revision 5.** Round 3 produced 2 critical, 8 major and 13
> minor findings, and two of them were empirical questions now settled by
> direct inspection (section 11): the Summary totals do cover both placeholder
> rows, and `drive.metadata.readonly` is a **restricted** scope. The second
> retired decision (c) above — the user chose the pre-seeded index instead on
> 2026-09-21. The substantive design changes are: the run state now **holds
> rows**, not just counts, so no exit path can forget an accepted row (C-A);
> an explicit intra-upload dedup rule (M-A); writes are never blanket-retried
> (M-B); reconciliation is specified against a recorded pre-append baseline as
> a multiset operation (M-G); the period constants are re-derived from six
> months of measured spans and pre-anchor rows are labelled by real intervals
> rather than a fixed 30-day step (M-E); and both placeholder categories are
> withheld from the AI's own option list (M-F).
>
> **What changed in revision 6.** Round 4 returned one critical and five
> majors, all internal-consistency or mechanism defects rather than objections
> to the direction. `rows` now exists in the run state from `split`, not
> `categorised`, because resolution precedes categorisation and the failure
> C-A exists for happens before it (C-C). `appending` is a one-way door, so a
> write error cannot resume down a path that re-appends a landed block (M-I).
> The reconciliation baseline is the first row this run may write, not the
> last row already there (M-J), and the positional shortcut is now validated
> with a `/sort` guard and a content-matching fallback, because position-based
> identity in a sorted block is round 2's K1 defect resurfacing inside its own
> cure (M-K). `seed_state.py` seeds boundary history from row dates, because
> marker-matching a sheet's Description column provably cannot work (M-L).
> And `create` is allowed only for the month after the newest one the index
> knows, which prevents most of the duplicate-sheet risk the user accepted
> without needing any Drive scope (M-N).
>
> **What changed in revision 7.** Round 5 returned no criticals and four
> majors, but tripped the loop's fix-churn breaker: 4.5, 4.6 and 4.7 had
> carried the blocking findings for two consecutive rounds, and the same
> append/reconcile contract had been mis-specified in three successive
> revisions — each time in a different single detail, each time in prose that
> read correctly. So those three sections are **rewritten holistically**
> rather than patched again, and the contract is now stated as a **numbered
> procedure** (4.6, "The append contract") that names every piece of state it
> reads, says where each is written, and states its invariant: *the ledger may
> over-record, never under-record*. The four majors: the ledger is now
> recorded **before** the write and the `written` flip happens last, closing a
> crash window that previously left a `written` period with no ledger entry
> and therefore no net against the next overlapping upload (M-O); the change
> detector is the recorded **prefix digest**, not a row count, because
> `compact_block` preserves the row count and so a count check passes
> precisely when a sort has happened (M-P); `newest(index)` is ordered
> chronologically by `label_sort_key`, not lexicographically, which would have
> made the bot refuse to create February 2027 (M-Q); and the registry's
> informational reads go through `lookup`, which never creates, so seeding a
> starting balance can no longer recursively create months (M-R).
>
> **What changed in revision 8.** The breaker's cold read, by a fresh reviewer
> with no loop history, found that the holistic rewrite had fixed every
> *ordering* question but that the same failure species had moved one layer
> down: the procedure was specified over a type it never defined. `RowTuple`
> is now a **canonical comparison form** with a single producer, `canonical()`,
> and `read_block` reads `UNFORMATTED_VALUE` and converts — without which an
> intended `12.34` would have been compared against a read-back `"€ 12,34"`,
> every reconciliation would have taken the fallback, and every fallback would
> have re-appended the whole block with the ledger already recording it (C1).
> `first_write_row` is now identity-only and `commit_append` recomputes its own
> append point, so the fallback cannot overwrite live data with a baseline that
> is stale by construction (C2). The dedup record and the **write audit** are
> now separate operations — the former before the write and permitted to
> over-record, the latter after it and exactly what landed — because undo is
> destructive and the over-record licence was only ever justified for dedup
> (M2). `sort_by_date` carries the `appending` refusal as its own precondition,
> so the pipeline's closing sort obeys it too (M1). `read_block` is positional
> with explicit blanks (M4), and `L8` may only be sourced from a month that is
> `written` or untouched (M3). The Phase 1 sandbox gains the one assertion no
> fake can make: the `RowTuple` round-trip against the real `nl_NL` workbook.
>
> **What changed in revision 9.** Round 7 returned no criticals and four
> majors, all bounded, and the reviewer gave a checkable reason why the
> "fix was right, one level too shallow" descent terminates here: `RowTuple`
> is four primitives, and there is no layer beneath a primitive type. The
> fixes: the procedure now binds `txs` and `intended` as parallel sequences,
> because the ledger's strong key needs bank fields a `RowTuple` provably
> cannot supply, and the reconcile branches were passing the wrong one (M-S);
> reconciliation audits the rows it *finds*, not only the rows it appends,
> closing a window where a crash between the write and the audit left rows
> permanently un-undoable (M-T); the compaction guard moved from
> `sort_by_date` down to `compact_block`, so `remove_rows` inherits it and
> `undo_upload.py` can no longer destroy the baseline a mid-write run needs —
> and `/cancel`'s message now *sequences* the remedies instead of offering two
> that contradict each other (M-U); and `canonical` is **total**, which a
> measurement turned from defensive to load-bearing: `02/2026` holds **70
> text-typed date cells** where every other sheet returns serials, so a
> `canonical` that assumed a serial would have raised on that sheet's prefix
> (M-V).
>
> **What changed in revision 10.** Round 8 returned no criticals and two
> majors. The first was mine: the `canonical` totality contract of revision 9
> had been written into the banner, the test list, the risk table, the log and
> the measurement — every place it was *justified* — and **not** into 4.5,
> the section that actually specifies it, because an edit script discarded the
> change when a later pattern in the same batch failed to match. 4.5 therefore
> still defined a two-case converter while section 5 asserted a total one, so
> the plan contradicted itself on the one point the previous two rounds
> existed to settle. It is now in 4.5 as a per-slot accepted-range table
> (M-W). The second: the `found` term added in revision 9 used multiset
> *membership* rather than multiplicity-respecting consumption, and
> `txs_of(remaining)` inverted a map that is not injective — two transactions
> can canonicalise identically and still carry different strong keys. Both
> reconcile branches now **partition indices of `txs`** with a runtime
> invariant, and `txs_of` is gone (M-X).

## 1. Problem

Today one CSV export must cover exactly one financial month. To process a
longer export the user edits `GSHEET_NAME` in `src/config/config_settings.py`,
rebuilds the container on the Pi, splits the CSV by hand, and repeats per month.
Row positions are tracked per user in the session file and re-detected on every
sheet switch, which is where most past bugs came from (`docs/IMPROVEMENT_PLAN.md`
P0/P1). `background_upload.py:162-245` and `:266-304` (`_load_row_positions` /
`_detect_current_positions`, called from five sites) are the root of that: the bot keeps its own idea of
where the next row is, instead of reading the sheet.

Goal: `/upload` in Discord with one or more ASN CSV exports covering any date
range, and the bot does the rest: split into financial months, find or create
the monthly sheet, categorise, write every row, flag the uncertain ones in the
sheet, and sort. No config edit, no container restart, no CSV surgery, and
nothing held back waiting for a human.

## 2. Decisions taken with the user, fixed

### 2026-09-20

| Topic | Decision |
|---|---|
| Month boundary | The booking date of the first DUO or Anamata salary **income** of a new cycle starts the new month. Same-day rows all belong to the new month. The 23-03 rows in the `04/2026` sheet were a manual exception, not the rule. |
| Sheet label | Boundary on day 15 or later names the **next** calendar month (DUO 24-03 → `04/2026`); day 1 to 14 names the boundary's own month. |
| Rows before the first boundary | Appended to the **previous** period's sheet. |
| Overlapping exports | Rows already uploaded are skipped and counted in the summary. The user normally exports "since last download", so this is a safety net. |
| Sheet creation | The bot creates missing months from the template. The service account cannot, so the bot moves to the **user's own Google account via OAuth**; the service account is retired. |
| Cache for Later | **Dropped**. |
| Confirmation gate | None before writing. In exchange the bot must detect a suspicious split and refuse to write (4.3), and every write must be undoable (4.6). |
| Test data | The user runs `scripts/make_fixture.py` on a real export and commits the reviewed output to `tests/fixtures/`. `scripts/sheet_shape.py` is the only inspection tool; it prints structure only. |

Rejected alternative, recorded so it is not re-proposed: keeping the service
account for read/write and adding an Apps Script web app under the user's
account to copy the template on request. Two moving parts, no OAuth app to
manage; the user chose OAuth instead.

### 2026-09-21

| Topic | Decision |
|---|---|
| Non-salary income from Anamata | Does not exist as a separate transaction: declaratie, vakantiegeld and similar are **batched into the monthly salary payment**. The spurious-boundary risk (round 1 C2) is therefore low, and `PERIOD_BOUNDARY_MIN_AMOUNT` stays as a cheap safety net rather than a load-bearing control. |
| Where the sheets live | One Drive folder `Financiën` (`1QoYs19vu04_DFIszlfWOJP7BoQLEtfaG`), with 2026 months directly in it and subfolders `2024` and `2025` holding the older ones. The whole folder is now shared with the service account. |
| **Uncertain transactions** | **Written to the sheet immediately** with the AI's description and category `! Nog in te delen !`. **The Discord review UI is removed entirely** — no `/review`, no `/pending`, no approval queue, no pending state. Follow-up is filtering the Category column in the sheet. Uploading must never block on a human. |
| Income placeholder | `! Nog in te delen !` is added to `IncomeCategory` and to the income category table of the template and the five populated 2026 months, so flagged income is summed like flagged expenses. |
| Sheet lookup | **Superseded on 2026-09-21 (second pass).** The original decision requested `drive.metadata.readonly` so months could be resolved by name. That scope is **restricted** (section 11), requiring a CASA security assessment — a paid third-party audit with annual revalidation — so it was withdrawn. The bot instead resolves a month through an explicit, authoritative `data/sheet_index.json`, pre-seeded with the 2026 sheet ids already collected (section 11). OAuth requests only `spreadsheets` and `drive.file`, neither of which is restricted. |
| Consequence accepted with that choice | The bot cannot check whether a sheet of the same name exists elsewhere in Drive before creating one, because it has no Drive read scope. A month the **user** creates by hand and does not `/months register` is invisible to the bot, which will create a second sheet for that label and write into it. The user was told this explicitly and accepted it: creation is announced in the run summary, `/months` prints the index, and the intended workflow is that the bot creates every month. Moving a sheet between Drive folders does not change its id, so re-filing never breaks the index. **Blast radius if it fires**: a whole month, around 100 rows, lands in a sheet the user is not looking at while their hand-made sheet stays empty — and because 4.4 step 7 reads the next month's starting balance from `previous_label`'s `Summary!E17` through the index, the duplicate also feeds a wrong `L8` into the following month. The adjacency guard in 4.4 removes the most likely path to this; what remains is the user hand-creating the next month and not registering it. |

**Why the review UI goes.** The user's requirement is that every transaction
ends up in the document and that nothing blocks the upload; follow-up happens
in the sheet, where the flag is visible and filterable. A five-month backlog is
about 450-500 rows (section 11), which is precisely the volume at which
one-by-one Discord review stops being a real flow. The cost is that the AI's
rejected guess for a flagged row is not offered anywhere; 4.9 keeps it in the
run record and the summary so the information is not lost.

### Service-account capability, re-verified 2026-09-21

Folder-level sharing did **not** change what the service account can create.
With the whole `Financiën` folder shared:

- `drive.files.copy` of the template, both into the folder and with no parent:
  **403 `storageQuotaExceeded`**, "The user's Drive storage quota has been
  exceeded". `about.get` reports `storageQuota.limit == "0"`.
- `sheets.spreadsheets.create`: **403 "The caller does not have permission"**.
- It *can* now list and open all 31 spreadsheets with `canEdit == true`, and
  walk the folder tree.

So the OAuth decision stands unchanged, and the new capability is only useful
for the one-off seeding and inspection scripts, which may keep using the
service account. Using it for *runtime* name resolution was offered to the
user as an alternative to the index and declined, because it would keep a
second credential alive on the Pi and reverse the "service account is
retired" decision above.

## 3. Definition of done

1. `pytest` green (section 5), including the two existing modules.
2. Sandbox end-to-end: the anonymised fixture (three or more boundaries) is
   uploaded through Discord against a sandbox template copy; the bot creates
   the missing month sheets, **every row lands in the sheet its date belongs
   to and no row is held back**, low-confidence rows carry
   `! Nog in te delen !` and are countable by filtering, `Summary` totals
   compute with no `#REF!`, the category dropdown works on the created sheet,
   the created month's `L8` equals the previous month's `E17`, a second upload
   of the same file writes nothing, and `scripts/undo_upload.py` run **after**
   the sort restores every **pre-existing** sheet to its pre-run content and,
   with `--drop-created`, leaves no sheet the run created. The one documented
   exception: if a period's reconciliation took the content fallback, undo
   coverage for that period is partial and the run summary said so (4.6).
3. Production: the backlog (05/2026 tail from 22-05-2026 to the current month)
   is processed from a single `/upload` on the Pi with no config change and no
   restart during the run.
4. The Pi runs on the OAuth token; the service account key is no longer
   referenced by the bot's config or by `run.sh`.
5. `grep -rn "background_upload\|pending_transactions\|transaction_prompt\|session_management\|DUMMY_CACHED" src` returns nothing.

## 4. Architecture

### 4.1 Data flow after the change

```
/upload f1.csv [f2 … f5] [force]  → in-flight guard → files saved under data/uploads/<upload_id>/
  → load + normalise each CSV (csv_helper); rows with an unparsable date are reported and dropped
  → concat, sort by date
  → collapse_within_upload → rows duplicated ACROSS attachments collapsed (max per file, not sum)
  → ledger.filter_new  → rows already in a sheet skipped and counted
  → split into periods (periods.py, given the persisted anchor)  ── SuspiciousSplitError writes nothing
  → anchor advanced to the last accepted boundary (anchor_before kept in the run state)
  → for each period, in date order:
       resolve sheet (sheet_registry: index hit, or create from template)
       categorise (regex + batch AI, chunks within the period)
       assign a category to EVERY row (4.9): confident → its category; otherwise → '! Nog in te delen !'
       plan_append per block → baseline (first_write_row, prefix) persisted
       run state → appending
       ledger.record_written  ── BEFORE the write; idempotent; may over-record, never under-record
       commit_append: one values_update per (sheet, block)
       ledger.record_audit  ── AFTER the write; exactly what landed; the undo record
       run state → written  ── only after every block of the period has committed
       progress line to the user's thread
  → writer.sort_by_date every touched sheet once, EXCEPT any sheet with a period still `appending`
  → summary embed per period (boundaries, created sheets, skips, flagged count and the
    AI guess that was discarded for each flagged row)
```

There is no second phase. When `/upload` returns, every accepted row is in a
sheet.

### 4.2 Google access: `src/finance_core/google_auth.py` (new)

Scopes, with Google's own classification (verified 2026-09-21 against
`developers.google.com/drive/api/guides/api-specific-auth`):

| Scope | Class | Why |
|---|---|---|
| `…/auth/spreadsheets` | **sensitive** | read and write any of the user's spreadsheets by id, including months the app did not create |
| `…/auth/drive.file` | **non-sensitive** | create the new month workbook, and move it into the folder where permitted |

**No restricted scope is requested, and none may be added without a decision
from the user**, because every restricted scope triggers a CASA security
assessment: a paid third-party audit that must be revalidated every 12 months.
Google classifies `drive`, `drive.readonly`, `drive.metadata`,
`drive.metadata.readonly`, `drive.activity(.readonly)` and `drive.scripts` as
restricted; only `drive.file`, `drive.appdata` and `drive.install` are not.
A sensitive scope needs written justification at verification but no audit, and
an unverified app **in production** shows Google's "unverified app" warning
once at consent and then works.

This is why the bot has no Drive listing capability at all, and why the sheet
index in 4.4 is authoritative rather than a cache.

- `get_credentials()`: loads `GOOGLE_OAUTH_TOKEN_PATH` (default
  `data/google/authorized_user.json`), refreshes via google-auth, and writes
  the file back after every refresh (Google may rotate the refresh token).
  Missing file or `RefreshError` → `GoogleAuthError` whose message names
  `scripts/google_login.py`. The bot never opens a browser.
- `get_gspread_client()`, `get_sheets_service()` and `get_drive_service()`
  share those credentials.
- `scripts/google_login.py`: installed-app local-server flow on the
  workstation using `GOOGLE_OAUTH_CLIENT_PATH` (`data/google/oauth_client.json`),
  writes the token with mode `0600`, prints the `scp` command for the Pi and
  the reminder that the OAuth app must be **In production** (in *Testing*
  Google expires refresh tokens after 7 days).
- File ownership on the Pi: `data/` is bind-mounted; the container runs as
  `appuser` (uid 1000, same as `pi`). Token and client files: owner `pi`,
  mode `0600`.
- `GOOGLE_AUTH_MODE = "oauth" | "service_account"` exists only during Phases
  1 to 3 so the old path still runs; removed in Phase 4.

Plan B, only if OAuth consent cannot be completed at all (the `spreadsheets`
scope is blocked rather than warned): fall back to the service account for
reads and writes to the months that already exist — section 2 verifies it can
open all 31 with `canEdit` — and have the user create each new month by hand
from the template, registering it with `/months register`. That is a degraded
but working bot, and it needs no new scope. Adding the full `drive` scope is
**not** plan B: it is restricted, so it costs a CASA audit and buys only what
the index already provides.

### 4.3 Periods: `src/finance_core/periods.py` (new, pure)

```python
@dataclass(frozen=True)
class Anchor:                # persisted in data/period_state.json by the pipeline
    boundary: date           # date of the last accepted boundary
    label: str               # "MM/YYYY" of the period it opened
    history: tuple[tuple[date, str], ...] = ()   # older (boundary, label), newest first

@dataclass
class Period:
    label: str
    start: date              # boundary date, or first row date for a leading remainder
    kind: Literal["leading", "closed", "open"]
    boundary_row: dict | None
    transactions: list[dict]

def split_into_periods(transactions, *, anchor: Anchor | None, markers, min_amount,
                       min_days, max_days, split_day, force=False) -> list[Period]
def label_for_boundary(d: date, split_day) -> str
def next_label(label) -> str;  def previous_label(label) -> str
def label_sort_key(label) -> tuple[int, int]   # (year, month) — never string order
class SuspiciousSplitError(Exception): boundaries: list[tuple[date, str]]; reason: str
```

The function is pure; the pipeline owns the anchor file and passes it in.
`transactions` arrive **after** `ledger.filter_new`, so every row the splitter
sees is new to the bot.

**`force` has one meaning**: it suppresses the checks in rules 4, 6 and 7. It
never changes how a row is labelled. Labels always come from
`label_for_boundary` for periods opened by an accepted boundary, and from the
anchor for rows outside those periods.

Rules, each with a test in `tests/test_periods.py`:

1. **Candidate boundary**: a `CRDT` row whose counterparty name or remittance
   matches a `PERIOD_BOUNDARY_MARKERS` pattern (default `[r"\bDUO\b", r"Anamata"]`)
   **and** whose amount is at least `PERIOD_BOUNDARY_MIN_AMOUNT` (default 250,
   below the smallest DUO payment). DUO repayments (`DBIT`) and
   "Salaris Janneke" from a private person are not candidates. Per the
   2026-09-21 decision, Anamata pays nothing outside the salary batch, so the
   amount floor is a safety net rather than a necessity.
2. **Clustering**: candidates sorted by date. The first candidate opens a
   cluster; a later candidate joins the cluster if it is less than `min_days`
   (20) after **the cluster's boundary date** (its earliest candidate), never
   measured from the previous candidate, so clusters cannot chain. The
   boundary date of a cluster is its earliest candidate (the user's rule).
   DUO on the 24th and salary on the 25th form one boundary on the 24th.
3. **Anchor continuity**: with an anchor, a first candidate less than
   `min_days` after `anchor.boundary` is the anchor's own boundary seen again
   (overlapping export) and opens no new period.
4. **Leading rows** (dated before the first accepted boundary, or all rows
   when there is no boundary and an anchor exists). **Real intervals first,
   arithmetic only as a fallback** — section 11 measures the last five periods
   at 29, 31, 26, 31 and 27 days, so any fixed step length is wrong:
   - rows in `[anchor.boundary, anchor.boundary + max_days)` get
     `anchor.label`;
   - rows before `anchor.boundary` are placed by `anchor.history`: a row in
     `[history[i].boundary, history[i-1].boundary)` gets `history[i].label`.
     This is exact, because those are the boundaries the bot actually accepted,
     or that `seed_state.py` read off the sheets;
   - only for a row older than the oldest known boundary does the arithmetic
     fallback apply — `previous_label` once per started `PERIOD_STEP_DAYS`
     (29, the measured mean, not 30) back from that oldest boundary — and only
     one such step is allowed before `SuspiciousSplitError`, unless `force`,
     in which case the same step rule labels it;
   - without an anchor at all, leading rows get `previous_label(first_label)`
     and the summary carries a warning line.

   The error case revision 4 would have produced on the most common path is
   now impossible: a row 31 days before the anchor boundary is one real period
   back and is labelled from `history`, where revision 4's `ceil(31/30) = 2`
   steps aborted the run and wrote nothing.
5. **No candidate, rows beyond the anchor window**: rows dated on or after
   `anchor.boundary + max_days` mean a boundary must have happened but is not
   in the file. This is a `SuspiciousSplitError` that `force` does **not**
   suppress, because no labelling rule exists for those rows; the message
   says "re-export from <anchor.boundary> so the DUO row is included". The
   deliberate escape is `scripts/seed_state.py --set-anchor`. Without an
   anchor, the split rule on the earliest row applies with a warning.
6. **Labels**: `label_for_boundary` per accepted boundary.
7. **Contiguity and length check**:
   - the label sequence, starting from `anchor.label` when known, must
     advance by exactly one month per boundary-opened period;
   - every `closed` period (opened by an accepted boundary and closed by the
     next one) must be at least `min_days` long; the `leading` remainder and
     the final `open` period are exempt;
   - any violation → `SuspiciousSplitError` listing every detected boundary
     (date, amount bucket, label) and nothing is written;
   - `force` suppresses this check; labels are unchanged, so an export of
     January plus March with February missing writes March into `04/2026`
     and the summary names the skipped month. A December bonus on 10-12
     after a `12/2026` period aborts instead of creating `01/2027`.
8. **Same-day**: rows dated on the boundary date belong to the new period
   whatever their order in the file.
9. Every transaction dict gets `period_label`; the count of rows in is the
   count out.

Anchor lifecycle: read at run start; **advanced once the split has passed its
checks — that is, on accepted boundaries at split time, not on written
periods.** A run whose every period then fails leaves the anchor advanced with
nothing written; that is deliberate and benign, because `anchor_before` is in
the run state and `undo_upload.py` restores it, and because `/resume` never
re-splits, so the advanced anchor is never consulted for rows this run already
labelled. The anchor is set to the last accepted boundary and its label if
later than the current anchor, **and the superseded anchor is pushed onto `history`**, so the
real intervals accumulate as the bot runs. The whole previous value is stored
as `anchor_before` in the run state and restored by `undo_upload.py`. Seeded
at cutover by `scripts/seed_state.py` (4.10), which takes **the earliest row
date in each populated sheet** as that month's boundary. That is exact by
construction: everything dated before the boundary went to the previous
sheet, so the earliest row *is* the boundary.

It deliberately does **not** marker-match the sheet, because that cannot work.
The monthly sheet's income block carries only Date, Amount, Description and
Category — there is no counterparty or remittance column — and the Description
is the one the bot itself wrote. Verified by running the real rules through
`apply_categorization_rules` (section 11): a DUO row becomes
`"Duo uitkering"` and an Anamata salary becomes `"Salaris Ezra"`, and neither
`r"\bDUO\b"` (case-sensitive against title-cased text) nor `r"Anamata"`
matches either string. Marker matching works at upload time, where the raw CSV
counterparty is `DUO Hoofdrekening`; it fails against the sheet. Seeding from
dates avoids the round-trip entirely. `seed_state.py` prints the boundaries it
found and requires the user to confirm them.

**Constants derived from section 11 rather than chosen.** The quantity the
forward window guards is **boundary-to-boundary**, which section 11 measures
at 30, 32, 27 and 32 days — so 27 to 32, not the 26-to-31 range of *populated*
spans. So: `PERIOD_MIN_DAYS = 20` (comfortably below 27),
`PERIOD_MAX_DAYS = 35`, and `PERIOD_STEP_DAYS = 29` for the fallback only.

Because real boundaries land anywhere in 27 to 32 days, **any** fixed forward
window leaves an ambiguous band — a row 33 days past the anchor could be a
late boundary's own period or the next one's. 35 resolves that band toward the
anchor deliberately: mislabelling a few late rows into the anchor's month is
recoverable by editing the sheet, whereas aborting the run writes nothing.
Revision 4's 40 pushed the band too wide, silently swallowing rows 32 to 39
days out that belong to the next month. A period outside 27-32 days is caught
by rule 7's contiguity check rather than mislabelled.

**The rules are validated against six months of real history** (section 11):
every 2026 sheet runs from the 23rd or 24th of the previous month to the 21st
to 23rd of its own, which is exactly what rules 1, 2 and 6 produce. The
production backlog walk required before Phase 2 tests are frozen is therefore
a confirmation, not a discovery: anchor `(24-04-2026, "05/2026")` with
`history` seeded from 23-03, 24-02, 23-01 and 24-12, leading remainder 22-05
to 23-05 into `05/2026`, then one boundary per month from 24-05 onward.

### 4.4 Sheet registry: `src/finance_core/sheet_registry.py` (new)

**Two operations, named distinctly so they cannot drift into each other:
`resolve` may create, `lookup` never does.** `lookup(label)` returns the
indexed spreadsheet or `None`; it is used wherever the registry is consulted
for *information*. `resolve(label)` is used only when a write target is
needed.

The bot has no Drive listing scope (4.2), so the registry is an **explicit,
authoritative index**. `data/sheet_index.json`:
`{"04/2026": {"id": "...", "created_by_bot": false, "created_at": "..."}}`.

`resolve(label)`:

1. **Index hit** → `open_by_key`, then verify before use: the title matches
   `GSHEET_NAME_PATTERN` and the `Transactions` header row 4 reads
   Date/Amount/Description/Category in B:E and G:J, else `SheetLayoutError`.
   A `SpreadsheetNotFound` (the user deleted or trashed it) is its own error
   naming the label and the stale id, never a silent re-create.
2. **Index miss** → `create(label)` when `GSHEET_AUTO_CREATE` is true **and
   the label is adjacent**, else `MissingSheetError` naming the label and
   pointing at `/months register`.

**Adjacency guard.** The bot only ever legitimately creates the month *after*
the newest one it knows about, so `create` is allowed only when
`label == next_label(newest(index))`, where `newest` is the maximum by
`label_sort_key` — `(year, month)` — and **never** by string order. Labels are
`"MM/YYYY"` strings, so a lexicographic maximum is wrong the moment a year
boundary appears: `max(["11/2026", "12/2026", "01/2027"])` is `"12/2026"`,
whose `next_label` is `"01/2027"`, which is already indexed, so `02/2027`
would look non-adjacent and the bot would refuse to create February 2027 —
recoverable only by editing config inside the image and rebuilding, which is
the loop section 1 exists to eliminate. Any other miss means something is already
wrong — the user made that month by hand, or the splitter produced a label
that should not exist — and a loud `MissingSheetError` is the right answer.
`GSHEET_CREATE_NONADJACENT` (default `False`) overrides it for a deliberate
gap-filling run. On an **empty** index `newest` is undefined, so adjacency
cannot be evaluated and any label is permitted; Phase 0 seeds six months, so
this state only arises on a fresh install.

A *full* pre-create guard would need a Drive-wide name search, which needs a
restricted scope, which the user declined (section 2) — but that is an
argument against searching Drive, not against checking what the bot itself
knows. Adjacency costs nothing and catches the most likely instance of the
accepted risk. What remains after it: the user hand-creates the *next* month
and does not register it, and the bot creates a duplicate of exactly that
month. Bounded by three things — every creation is named in the run summary
embed, `/months` prints the index on demand, and `create` records
`created_by_bot: true` so the two cases are distinguishable afterwards.
`undo_upload.py` removes the rows it wrote; it removes the created
spreadsheet and its index entry **only with `--drop-created`** (4.6), so
without that flag a duplicate sheet survives in Drive and in the index and
the next run resolves it again.

**The index is authoritative and must be backed up.** It cannot be rebuilt by
listing Drive. It is pre-seeded in Phase 0 from the 31 ids already collected
(section 11), the bot appends every month it creates, and
`/months register <label> <url>` covers a month created by hand. Losing
`data/` therefore costs a re-seed, not a re-derivation — which is why 4.10
classifies it as authoritative and round 2's n12 stands rather than being
retired.

`create(label)`, in this order:

1. `spreadsheets.get(GSHEET_TEMPLATE_ID, fields=properties)` and
   `spreadsheets.create` with the title **and** the template's `locale`,
   `timeZone` and `autoRecalc` (verified `nl_NL`, `Europe/Monaco`,
   `ON_CHANGE`); a default `en_US` workbook would re-parse amounts
   differently in the sort;
2. `sheets.copyTo` the template's `Transactions` tab, then rename the copy
   (`Copy of Transactions`) to `Transactions`;
3. `sheets.copyTo` the template's `Summary` tab, then rename to `Summary`;
   its `SUMIF`s reference `Transactions`, which now exists;
4. delete the default `Sheet1`, move `Summary` to index 0;
5. `files.update(addParents=GSHEET_FOLDER_ID, removeParents=root)`. Under
   `drive.file` the app has full access to the file it just created but **no
   write access to the folder**, so this call may well 403 in the steady
   state; Phase 1 establishes which. Either way it does not fail the run: the
   sheet stays in My Drive root, the index holds its id, and the bot keeps
   working. The summary embed names any month left in root so the user can
   file it, and filing it by hand does not change the id. `files.copy` of the
   template is never used;
6. fidelity check, all assertions or the new file is deleted and
   `SheetLayoutError` raised (three failures in Phase 1 trigger plan B):
   header row 4 as above; `Transactions!E5` and `!J5` carry the
   `ONE_OF_RANGE` validation; workbook locale, time zone and `autoRecalc`
   equal the template's; the created file's `parents` is recorded (in the
   folder, or root with a warning); and — replacing the weaker
   label-presence check of revision 4 — a **behavioural totals check**: write
   one flagged expense row and one flagged income row of a known test amount,
   assert `Summary!E26`, `Summary!K26` and `Summary!E17` each move by that
   amount and no cell reads `#REF!`, then remove the two rows and assert the
   totals return. This proves the placeholder categories actually reach the
   monthly totals rather than merely appearing in a table;
7. starting balance, via **`lookup`, never `resolve`** — otherwise seeding
   `L8` could *create* the previous month as a side effect, and that creation
   would run its own step 7 and recurse backwards until an index hit. The
   adjacency guard hides this (the previous label is `newest(index)` by
   definition), but `GSHEET_CREATE_NONADJACENT = True` exposes it: creating
   `09/2026` against an index topping out at `06/2026` would silently create
   `08/2026` and `07/2026` as well. So: if `previous_label(label)` is **in the
   index** and that sheet is **either `written` in this run or untouched by it**,
   and is not empty, read its `Summary!E17` (rendered value) and write it to
   the new `Summary!L8`; otherwise list the month under "set the starting
   balance" in the summary embed.

   The condition is deliberately "`written` or untouched" rather than "not
   `failed`": since `appending` is a one-way door (4.7), a period whose write
   raised is never marked `failed`, so a "not `failed`" test would pass in
   exactly the state where the previous month is **half-written**. `E17` is a
   live formula over that month's totals, so a half-written month yields a
   real, plausible, wrong starting balance — which nothing would detect, and
   which section 2 already names as part of the accepted blast radius;
8. record it in the index. **Nothing is written to the index before this
   step completes**, so a fidelity failure at step 6 — which deletes the new
   file — cannot leave a half-registered month behind.

`register(label, url_or_id)` and `list_months()` back the `/months` command.
In-process lock so two runs cannot create the same label twice.

**Retry scope.** A small `with_retry` helper (429 and 5xx, exponential backoff
5/15/45 s, three attempts) wraps **reads, resolves, `files.*` and
`spreadsheets.create`/`copyTo` only**. It must never wrap `values_update`:
that call is not idempotent, and a 5xx or dropped connection *after* the
mutation landed would append the block twice while reporting success. Write
failures are handled instead by the reconciliation path of 4.6, which is
idempotent by construction. This is the one place revision 4's fix for round
1's M3 (restoring the deleted queue's backoff) reintroduced a double-write.

### 4.5 Writer: `src/finance_core/sheet_writer.py` (new, replaces the row-position machinery)

**Block assignment**, stated once because nothing else states it: a row whose
`credit_debit_indicator == "CRDT"` goes to the income block `G:J`, every other
row to the expense block `B:E`. Unchanged from `export.py:121` (and `:294`).

A *block* is one of the two four-column regions of a `Transactions` tab, whose
data begins at `GSHEET_DATA_START_ROW` (5). The writer only ever appends and
compacts; it never inserts, and it never writes above
`GSHEET_DATA_START_ROW`.

#### `RowTuple`: the one canonical comparison form

Every comparison in this plan — the prefix digest, both multiset subtractions
in 4.6, and `undo`'s content matching — compares a row the bot is about to
write against a row read back from Sheets. Those two are **not** naturally
comparable, and pinning them down is the single most important definition in
the design:

- `format_transaction_for_sheet` returns `[date_str, float, description,
  category]` — a Python **float** (`google_sheets.py:197`);
- writes go out `USER_ENTERED` into an `nl_NL` workbook whose amount cells
  carry `[$€]#,##0.00` (section 11);
- a gspread `get` returns **formatted strings** by default, so the same cell
  reads back as `"€ 12,34"` against an intended `12.34`, and the date as the
  sheet chooses to render it.

Compared naively, nothing ever matches. Every reconciliation would fail its
prefix check, fall through to the content fallback, compute
`remaining == intended`, and **re-append the whole block** — with the ledger
already recording those rows, so the duplicates would be invisible to
`filter_new` forever. `undo` would match nothing and silently remove nothing.
So:

```python
RowTuple = tuple[str, str, str, str]
#   0 date        ISO "YYYY-MM-DD"
#   1 amount      f"{value:.2f}", '.' decimal separator, sign preserved
#   2 description str, stripped
#   3 category    str, stripped

def canonical(row) -> RowTuple      # the ONLY producer of a RowTuple
```

`canonical` is the only function that produces a `RowTuple`, and **nothing in
the plan compares anything else**. It is applied to the intended rows, to
`commit_append`'s return and to `remove_rows`' arguments. `read_block` and
`plan_append` canonicalise **internally** and are typed as returning
`RowTuple`s already, so `canonical` is never applied to their output a second
time — it is not idempotent, since an ISO date fed back through a
`DD-MM-YYYY` parse would not round-trip.

A `RowTuple` is a **comparison form only**. It is never the source of the
ledger's strong key, nor of anything else needing bank fields: it carries no
counterparty and no remittance, and its description is AI-generated and not
invertible. 4.6's procedure therefore keeps transactions and `RowTuple`s as
parallel sequences rather than mapping back from one to the other.

**`canonical` is total.** `read_block` reads
`valueRenderOption=UNFORMATTED_VALUE`, and what comes back is not uniform.
Measured across the five populated 2026 sheets (section 11): the date column
returns a serial on four of them but **text on 70 cells of `02/2026`**, all in
`DD-MM-YYYY`; the amount column returns `int` for whole values and `float`
otherwise. So each slot accepts a range and never raises:

```
canonical is TOTAL. Per slot, accepted inputs and their conversion:
  date      serial int/float   -> ISO, via the workbook epoch
            "DD-MM-YYYY"       -> ISO        (02/2026 holds 70 of these; section 11)
            "YYYY-MM-DD"       -> unchanged
  amount    int | float        -> f"{v:.2f}"
            numeric string     -> parsed, then f"{v:.2f}"
  desc/cat  any                -> str(v).strip()
  ANY SLOT  anything else      -> str(v).strip()        # never raises
```

The catch-all is safe because both sides canonicalise identically: a genuinely
unconvertible pre-existing cell simply never equals an intended row, which is
the harmless direction. `DD-MM-YYYY` is handled **explicitly rather than by the
catch-all** because it must canonicalise to the same ISO string as the serial
the bot writes for the same day — otherwise `undo`'s content matching would
fail against any hand-typed row.

Without totality, `plan_append` — which canonicalises a block's
**pre-existing** rows, the population most likely to have been hand-edited —
would raise on `02/2026` and fail the period, with an error reading as a type
error rather than as "a date in this sheet is stored as text".

This keeps every comparison independent of locale, of the cell's display
format and of `USER_ENTERED` re-parsing.

Fakes cannot prove this. `FakeWorksheet` is written by the same person as the
implementation and will agree with whatever it does, so the round-trip is
asserted **against the real API** in Phase 1 (section 6): write two rows to
the sandbox month, read them back, and assert
`canonical(intended) == read_block(...)[-2:]` under the real `nl_NL` workbook.
That assertion is what actually settles whether 4.6 is implementable.

```python
@dataclass(frozen=True)
class BlockBaseline:            # recorded per block, before any values_update
    first_write_row: int        # IDENTITY BOUNDARY ONLY — never a write position
    prefix: tuple[RowTuple, ...]   # positional, rows START .. first_write_row - 1

def plan_append(spreadsheet, block) -> BlockBaseline
def commit_append(spreadsheet, block, rows) -> list[tuple[LedgerKey, RowTuple]]
def read_block(spreadsheet, block) -> list[RowTuple]
def compact_block(spreadsheet, block, rows) -> None
def sort_by_date(spreadsheet) -> None
def remove_rows(spreadsheet, block, rows) -> tuple[int, int]   # (removed, not_found)
```

- **`plan_append`** reads the block once, computes
  `first_write_row = last non-empty + 1`, floored at `GSHEET_DATA_START_ROW`,
  and captures `prefix` — the positional sequence of `RowTuple`s for rows
  `START` through `first_write_row - 1`. Both are returned as a
  `BlockBaseline` and persisted by the pipeline **before** any write.
  `first_write_row`, not the last used row, is the identity boundary: the last
  used row holds a pre-existing row, and including it would attribute another
  row to this run and drop an intended one. On an empty block
  `first_write_row` is `GSHEET_DATA_START_ROW` and `prefix` is empty, which is
  well defined where "last non-empty" is not. `prefix` is persisted **as a
  SHA-1 digest** of that positional sequence, never as the sequence itself,
  because the digest is exactly what 4.6 step 2 compares.

  **`first_write_row` is an identity boundary and never a write position.**
  Conflating the two is what produced the earlier off-by-one revisions, and it
  would be actively destructive in the reconciliation fallback, which is
  reached exactly when the block is known to have moved — a stale
  `first_write_row` then points into the middle of live data.
- **`commit_append`** takes no baseline. It calls `ensure_capacity` (resize,
  50-row buffer), **recomputes its own append point** as `last non-empty + 1`
  immediately before writing, and issues **one** `values_update` for the
  block. It returns the `(ledger_key, RowTuple)` pairs actually written, which
  is the input to `record_audit` (4.6). It does **not** sort, and it is
  **never** wrapped in `with_retry` (4.4): `values_update` is not idempotent,
  so a failure is reconciled, never retried blind.
- **`read_block`** returns **one entry per sheet row** from
  `GSHEET_DATA_START_ROW` to the last non-empty row, with an internal blank
  row represented as an explicit empty tuple, so index *i* is always sheet row
  `START + i`. `prefix` is the same positional sequence. Without this, the
  slice in 4.6 step 2 — a row offset indexing a tuple sequence — would be off
  by the number of blanks and would fail the digest spuriously, pushing the
  normal recovery path into the fallback. Internal blanks can arise
  even though no block has one today (section 11): the legacy un-compacted sort
  is what would introduce one.
- **`compact_block(spreadsheet, block, cells)`** rewrites a block from
  `GSHEET_DATA_START_ROW` with the given rows and clears the tail to the
  previous last row.

  **Its payload is raw cell values, never `RowTuple`s, and it writes
  `valueInputOption=RAW`.** This is the one place the two row representations
  must not be confused. A `RowTuple` is a *comparison* form: locale-independent
  by construction, with the amount as `f"{v:.2f}"` — a **period** decimal
  separator. The workbook is `nl_NL`, where `.` is the thousands separator, so
  handing `RowTuple`s to a `USER_ENTERED` write would re-parse every amount in
  a block that was previously correct. Since `sort_by_date` and `remove_rows`
  both compact, and both touch rows they did not write, that would corrupt
  amounts on a routine end-of-upload sort.

  So `read_block` returns **both** representations — the canonical
  `RowTuple`s for matching and sorting, and the underlying unformatted cells
  (date serials, `int`/`float` amounts) for writing back — and `compact_block`
  receives the latter. `RowTuple`s are used for the sort key and for
  `remove_rows`' content matching only. `RAW` is safe for those values because
  they are already the workbook's own native types, which is exactly why the
  raw form is the one carried through.

  (Whether Sheets would parse `"12.34"` as `12.34` or `1234` under `nl_NL`
  with `USER_ENTERED` is unresolved on paper and does not need to be: the raw
  path is correct either way. Phase 1's round-trip assertion settles it
  incidentally.) Shared by
  `sort_by_date` and `remove_rows`. Note that compaction **preserves the
  non-empty row count** — it removes blanks and reorders — which is why a row
  count is not a usable change detector (4.6).

  **Precondition, and it belongs here rather than on the callers: it refuses
  for any spreadsheet with a period at `appending` in any open run.**
  Compaction shifts every row and so invalidates that period's positional
  baseline. Attaching the guard to `compact_block` means `sort_by_date` **and**
  `remove_rows` both inherit it, and no future compacting caller can miss it —
  which matters because `undo_upload.py` calls `remove_rows`, so a guard on
  `sort_by_date` alone would leave undo free to destroy the baseline the run
  needs. `sheet_writer` does not import the pipeline's run state: the caller
  passes an `is_appending(spreadsheet_id) -> bool` predicate supplied by
  `export.py`, and 4.8's `/sort` refusal is a consequence of this rule rather
  than a separate one.
- **`sort_by_date`** reads both blocks, sorts chronologically **on the
  canonical ISO date** and `compact_block`s **the raw cells** in that order, so
  a blank row inside a block cannot leave a stale tail — the bug the current
  `sort_transactions_by_date` has (section 11). Sorting on the canonical date
  and writing the raw values is what keeps a sort from re-parsing amounts; see
  `compact_block` above. A created workbook must still share the template's
  locale, because the rows the bot *appends* go out `USER_ENTERED`.

  Its precondition is the one stated on `compact_block` above, which
  `sort_by_date` inherits: sorting reorders a block whose positional baseline a
  mid-write run's recovery depends on (4.6).
- **`remove_rows`** removes **one occurrence per given tuple, and never more
  occurrences of a tuple than were passed** (multiplicity respected), then
  compacts. A tuple it cannot find is **skipped, not an error**; the return
  value is `(removed, not_found)` and `undo_upload.py` reports both. This
  matters because the audit can legitimately name a row that is not in the
  sheet (4.6), and because removing a pre-existing row that merely *equals* a
  recorded one would destroy the user's data.
- A per-spreadsheet `threading.Lock`; called from async code via
  `asyncio.to_thread`. Failures append to `data/failed_uploads.json` with
  `period_label` and `upload_id`.

The `manually_switched` sign rule inside `format_transaction_for_sheet` is
**vestigial**: only the deleted review UI's switch button ever set that flag.
It is left in place because it is harmless, but nothing can set it and no new
path is added that could.

Removed: `GoogleSheetsUploadQueue` and all of `background_upload.py`,
`sheet_positions`, `/resetsheet`, `queue_cached_replacement`,
`start_upload_queue()` in `bot.py`, and the dead, destructive
`write_transactions_to_sheet` / `export_to_google_sheets` pair in
`google_sheets.py` (section 11). `GoogleSheetsExporter` shrinks to formatting
and capacity and takes a `Spreadsheet`; `google_sheets.py` no longer imports
`GSHEET_NAME` (this import change lands in Phase 1).

### 4.6 Ledger, write audit and the append contract: `src/finance_core/ledger.py` (new)

With no review queue there is no `pending` state: the ledger records only what
is in a sheet. `data/upload_ledger.json` holds

- a **strong** key `sha1(booking_date | amount | counterparty | remittance)`,
  where remittance is the field **as the bank wrote it, before
  `normalize_csv_data` rewrites it**. That function substitutes
  `SPAARPOT_UUID_MAP` entries and repairs `verzekeri` in place, so keying on
  the normalised text would change the key of an already-recorded transaction
  the moment a map entry is added, and `filter_new` would stop recognising it.
  `csv_helper` carries the pre-normalisation remittance alongside the
  normalised one purely for the key. For that to hold, **`normalize_csv_data`
  stops rewriting the upload in place** and writes a normalised copy beside it
  (`<name>.normalised.csv`), leaving the original bytes intact. Today it
  rewrites the file (`csv_helper.py:127-138`), so on the one path that
  re-reads a retained upload — `/resume` of a run that crashed before the
  split — the "pre-normalisation" field would already be normalised, the
  strong key would differ from the one a fresh export of the same transaction
  produces, and a later overlapping upload would write the row again. Semantics are **multiset**: per key and
  label, a count and a list of `{upload_id, written_row}`. Two identical
  coffees on one day are two occurrences. ASN column 15
  (`bank_sequence_no`) joins the key **only if** the Phase 0 check shows it
  stable across two exports of the same transaction; nothing depends on it.
- a **weak** key `booking_date | abs(amount) | block` → count per label,
  filled for every strong record and by `scripts/seed_state.py` from the
  already populated sheets, which is the only way to recognise rows the old
  pipeline wrote, since their descriptions are AI-generated and not
  reproducible.

Operations:

- **`collapse_within_upload(files) -> txs`**, before `filter_new`. Two
  attachments in one `/upload` can overlap — covering a five-month backlog
  from ASN's export UI plausibly needs several files, and up to five are
  allowed. Both copies are unknown to the ledger, so both would pass
  `filter_new` and both would be written. The rule: count occurrences of each
  strong key **per file**, then take the **maximum across files, never the
  sum**. One row present in both of two overlapping exports collapses to one;
  two genuine same-day identical rows appear twice in *each* file covering
  that date and correctly stay two. Collapsed duplicates are counted in the
  summary separately from ledger skips, because they mean overlapping
  attachments rather than a re-upload.
- **`filter_new(txs) -> (new, skipped)`**: strong hit in **any** label → skip
  ("already uploaded"). Else weak hit in a **seeded** label with remaining
  count → skip ("probably already in `04/2026`"). Skips whose label differs
  from the row's computed label are reported on their own line (the
  `04/2026` ↔ `05/2026` seam).
- **`record_written(upload_id, label, txs)`** — the **dedup** record.
  **Idempotent**, keyed on `(upload_id, strong_key, label)`, so re-recording
  the same run's rows is a no-op. Idempotence is what lets the commit sequence
  below record *before* it commits, and the invariant permits it to
  over-record.
- **`record_audit(upload_id, sheet_id, block, pairs)`** — the **undo** record,
  and deliberately a **separate operation written after `commit_append`
  returns**, from exactly the pairs it returned.

  These must not share one record. The invariant that the dedup ledger may
  over-record is justified only for `filter_new`, where a spurious entry costs
  a skipped row. `undo` is destructive and content-addressed: an audit entry
  for a row that was never written would have `remove_rows` delete whichever
  row happens to match that tuple — the user's real data. So the dedup record
  is written before the write and may be wrong; the audit record is written
  after and is exactly what landed.
- **Write audit**: `runs[upload_id] = {anchor_before, sheets: {sheet_id:
  {block: [(key, RowTuple)]}}}`. `scripts/undo_upload.py <upload_id>` calls
  `remove_rows` per (sheet, block) with the recorded tuples — content-addressed,
  so an intervening sort is irrelevant — reports `(removed, not_found)`, and
  restores `anchor_before`. It does **not** delete a sheet the run created, nor
  its index entry, unless `--drop-created` is passed, in which case it removes
  index entries whose `created_by_bot` is true for that `upload_id` and trashes
  those spreadsheets. This is the undo the removed confirmation gate owes the
  user; it is built in Phase 1 next to the ledger.

#### The append contract

Everything above and in 4.5 exists to serve one contract, stated here as a
procedure rather than as prose, because three successive revisions of this
plan described it in English and each English version was subtly wrong.

**Invariant: the ledger may over-record, never under-record.** An
over-recorded ledger skips rows that really are in the sheet, which costs
nothing. An under-recorded ledger writes them a second time, silently, on the
next overlapping upload — and since the weak key only backstops *seeded*
labels, a month the bot created has no net at all.

Per period, per block, in this order:

```
Let START    := GSHEET_DATA_START_ROW  (5)
Let txs      := the period's transactions for this block   # bank fields; ledger keys
Let intended := [canonical(t) for t in txs]                # RowTuples; comparisons only
      -- txs[i] and intended[i] are the SAME row in two representations.
      -- Ledger writes always take txs. Comparisons always take intended.
         A RowTuple cannot produce a strong key: no counterparty, no remittance.

COMMIT (first attempt), per block
  1. baseline := plan_append(sheet, block)                 # reads the block
  2. persist baseline (first_write_row, prefix) and txs into the run state
  3. run state: period -> appending
  4. ledger.record_written(upload_id, label, txs)          # BEFORE the write; may over-record
  5. pairs := commit_append(sheet, block, txs)             # recomputes its own append point
  6. ledger.record_audit(upload_id, sheet, block, pairs)   # AFTER; exactly what landed
  7. run state: period -> written                          # only after every block commits

RECONCILE (on /resume of a period at `appending`), per block independently
  1. present := read_block(sheet, block)                   # positional; index i == row START+i
  2. if digest(present[: first_write_row - START]) != prefix:
         goto 5                                            # the block moved
  3. landed := multiset(present[first_write_row - START :])
     -- PARTITION THE INDICES OF txs, consuming from landed with multiplicity.
     -- Never a membership test: two identical intended rows must not both
     -- count as found when only one of them landed.
     avail := landed.copy();  found_idx := []
     for i in 0 .. len(intended)-1:
         if avail[intended[i]] > 0:  avail[intended[i]] -= 1;  found_idx.append(i)
     remaining_idx := [i for i in 0 .. len(intended)-1 if i not in found_idx]
     -- INVARIANT, asserted at runtime:
     --   len(found_idx) + len(remaining_idx) == len(intended)
  4. pairs := commit_append(sheet, block, [txs[i] for i in remaining_idx])
     found := [(key(txs[i]), intended[i]) for i in found_idx]
     ledger.record_audit(upload_id, sheet, block, pairs + found)
     ledger.record_written(upload_id, label, txs); return
  5. FALLBACK (content-addressed, order-independent):
     -- same index partition, against the whole block instead of the tail
     avail := multiset(present).copy();  found_idx := []
     for i in 0 .. len(intended)-1:
         if avail[intended[i]] > 0:  avail[intended[i]] -= 1;  found_idx.append(i)
     remaining_idx := [i for i in 0 .. len(intended)-1 if i not in found_idx]
     pairs := commit_append(sheet, block, [txs[i] for i in remaining_idx])
     ledger.record_audit(upload_id, sheet, block, pairs)   # pairs ONLY - see below
     ledger.record_written(upload_id, label, txs)
     report "content fallback used; undo coverage for this period is partial"
```

Notes that the procedure makes unambiguous, and that the prose versions did
not:

- **Record at 4, commit at 5, audit at 6, flip at 7.** A crash anywhere
  before 7 leaves the period `appending`, which `/resume` reconciles. A crash
  between 4 and 5 leaves an over-recorded dedup ledger — permitted by the
  invariant, and corrected by reconciliation finding `landed = ∅` and
  appending everything. Flipping to `written` before recording would be
  unrecoverable, because `written` is the one status `/resume` skips. The
  audit at 6 is deliberately *after* the write, so it never names a row that
  is not there.
- **The reconcile branches partition indices, never tuples.** `found_idx` and
  `remaining_idx` together account for every element of `txs` exactly once,
  and the invariant is asserted at runtime. A membership test would
  double-count the plan's own recurring example — two same-day rows that
  regex-categorise identically produce the same `RowTuple`, so when one landed
  and one did not, membership names both as found while `remaining` correctly
  holds one. Indices also remove the need to map a `RowTuple` back to its
  transaction, which is impossible in general: two different transactions can
  canonicalise identically and still have different strong keys, because a
  no-capture rule template such as
  `r"gebruik betaalrekening": ("ASN Gebruikskosten", …)` yields a fixed
  description whatever the counterparty was.
- **Reconciliation audits what it *finds*, not only what it appends**, which
  is the `found` term in step 4. A crash between 5 and 6 leaves rows in the
  sheet with no audit entry; reconciliation then computes
  `landed = intended` and `remaining = ∅`, so `commit_append` returns no
  pairs, and auditing only those would leave the audit permanently empty for
  rows that are demonstrably in the sheet. `undo` would then silently reverse
  part of a run — worse than refusing, since undo is the whole consideration
  the user received for giving up the confirmation gate. Auditing `found` is
  exact on this path for the same reason the path itself is trusted:
  everything at or after `first_write_row` provably belongs to this run.
- **The fallback deliberately does not audit `found`.** There the block has
  moved, so a match against `present` may be a coincidental pre-existing row;
  auditing it would have `undo` delete the user's data, which is exactly the
  destructiveness the record/audit split exists to prevent. So the fallback
  audits only what it appended and reports that undo coverage for that period
  is partial. This asymmetry is the plan's own reasoning about the two paths,
  applied consistently.
- **`commit_append` never writes at `first_write_row`.** It recomputes its own
  append point immediately before the `values_update`. This is what makes step
  5 safe: the fallback runs precisely when the block is known to have moved,
  so the recorded `first_write_row` points into live data, and writing there
  would overwrite the user's rows. It also makes step 4 safe on a partially
  landed block.
- **There are two blocks and therefore two `values_update` calls per period.**
  Reconciliation runs per block, so the expense block landing and the income
  block failing is an ordinary case, not an edge one.
- **The prefix, not a row count, is the change detector.** `compact_block`
  preserves the non-empty row count, so a count comparison passes precisely
  when a sort has happened. The prefix digest changes, because this run's rows
  shift down into the prefix window.
- **The positional shortcut is round 2's K1 defect** — position-based identity
  in a structure whose positions are deliberately unstable — so it is
  validated at step 2 rather than assumed, and `/sort` additionally refuses
  while any period is `appending` (4.8). The fallback at step 5 is safe
  against reordering but weaker in one specific way: a pre-existing row whose
  tuple equals an intended row makes that intended row look already-present,
  so it is **dropped**. When the fallback runs, the summary says so and tells
  the user to compare the period's row count against the sheet.
- `ensure_capacity`'s resize happens inside `commit_append`, after the
  baseline is recorded and while the period is `appending`, so a resize
  failure reconciles to `landed = ∅` like any other write failure.

### 4.7 Pipeline: `src/finance_core/export.py`

`process_upload(upload_id, interaction, force)` replaces `process_csv_file`.

**The run state holds rows, not just counts.** With the review UI gone there
is no other place an accepted-but-unwritten row can live.
`data/runs/<upload_id>.json`:

```
{files, anchor_before, force, started_at,
 periods: [{label, sheet_id,
            status: split | resolved | categorised | appending | written
                    | failed(reason) ,
            rows: {expenses: [...tx...], income: [...]},
            baseline: {expenses: {first_write_row, prefix}, income: {...}},
            flagged: [{key, ai_category, ai_confidence}],
            last_error: <str|null>,
            counts}]}
```

**`rows` is populated at `split`**, straight from `Period.transactions`, and
replaced by the categorised versions at `categorised`. It is cleared only at
`written`. The timing matters: 4.1's per-period order is resolve → categorise
→ append, so a period that fails at *resolution* was last at `split`, and a
`GoogleAuthError` that stops the run leaves every un-started period at `split`
too. If `rows` first appeared at `categorised`, neither could be recovered,
because `/resume` is forbidden to re-split. Rows therefore exist from the
first status onward, which is what makes every exit path recoverable.

`baseline` is written by 4.6's COMMIT step 2 and is what RECONCILE reads.

- **In-flight guard**: a module-level `current_run` (single-process bot). A
  second `/upload` while one runs is refused with "a run started at HH:MM is
  in progress". That guard is in memory and is therefore released by a
  restart, which is correct — but a restart can leave an *earlier* run with an
  unreconciled `appending` period, and a new upload writing to that sheet
  would invalidate its positional baseline. So `/upload` also **refuses when
  any open run has a period at `appending`**, naming the run and the period
  and pointing at `/resume`. This is the same precondition `/sort` and
  `/cancel` enforce.
- The ephemeral reply is "processing, results follow in your thread"; every
  period completion posts one line to the user's `Approvals-<name>` thread,
  because the interaction token dies after 15 minutes. The thread keeps its
  name; it is now a progress log, not an approval surface.
- **Per-period isolation**: a period failing at **resolution** is marked
  `failed(reason)` and the run continues with the others. A period that has
  entered `appending` is **never** marked `failed` — `appending` is a one-way
  door whose only exit is `written`, and a raising `values_update` keeps the
  period `appending` and records `last_error`, so `/resume` always reconciles
  instead of re-appending a block that may already have landed.
  `GoogleAuthError` stops the run immediately. `SheetLayoutError` deletes the
  orphan copy (4.4).

  **A write failure does not stop the run, and the run must not then sort that
  sheet.** The period stays `appending`; the remaining periods proceed; and
  the closing sort is **skipped for that period's spreadsheet only**, because
  `sort_by_date` refuses for any sheet with an `appending` period (4.5) — the
  closing sort is the same operation as `/sort` and obeys the same
  precondition. The summary says the sheet is left unsorted pending `/resume`.
  Without this the most likely failure in the whole design — one block's write
  returning 5xx — would have the run itself destroy the baseline that period's
  recovery depends on, forcing `/resume` down the fallback path.
- **AI budget**: `AI_RUN_MAX_MINUTES` (initial 30, re-sized in Phase 2 from a
  timed 40-row chunk on the Pi) for the whole run, and
  `AI_PER_TX_FALLBACK_LIMIT` (10): a failed chunk falls back to per-row AI
  only up to that many rows. Precategorised context and relationship
  detection stay within the period.

  What happens when the budget trips is a **choice** the plan makes
  explicitly: `AI_BUDGET_TRIP_ACTION`, default `"write_flagged"`. With
  `"write_flagged"` the remaining rows are still written, flagged
  `! Nog in te delen !`, with whatever description the bank text yields — this
  honours the never-block decision, at the cost of a batch of rows whose
  descriptions are raw remittance text that the bot will never revisit
  (section 8). With `"stop"` the remaining **un-started** periods stay `categorised` in the
  run state and are reported, so the user decides whether to `/resume` later.
  The budget trips inside a period's chunk loop, so the **period that is
  running when it trips always finishes under `write_flagged` semantics** —
  its uncategorised remainder is written flagged rather than left in an
  undefined state. `"stop"` affects only periods not yet begun. Without this,
  a tripping period could be resumed as `categorised`, which never
  re-categorises, and rows would be written with no category at all.
- **Resumability**: state is written after each status transition. The
  uploaded files stay under `data/uploads/<upload_id>/` until **every** period
  is `written` or explicitly discarded — not merely until the run "completes",
  since a run with one failed period and three written ones would otherwise
  delete the source of the rows still owed. `/resume [upload_id]` resumes the
  newest run that is neither fully written nor abandoned, or the named one;
  `/status` lists them when more than one is open.

  | Status | `/resume` does |
  |---|---|
  | `written` | skip |
  | `appending` | RECONCILE per block (4.6) |
  | `failed(reason)` | re-run from resolution, using the rows held in the run state |
  | `categorised` | re-run from resolution; never re-categorise |
  | `split`, `resolved` | re-run from resolution, using the rows held in the run state |

  A run whose `periods` list is **empty** — a crash before the split — has
  nothing to iterate and nothing at risk: no row was written, no label was
  committed, the anchor had not advanced. `/resume` re-runs such a run from
  the start, re-splitting from the retained files, because re-splitting is
  safe precisely when nothing has been acted on. It never reports success on
  an empty run.
- **`/cancel` cannot silently orphan a write.** It refuses while any period is
  `appending`, naming the period and **sequencing** the remedies rather than
  offering a choice: run `/resume` first to reconcile, then
  `scripts/undo_upload.py` if the run should be reversed. The order matters —
  undo calls `remove_rows`, which compacts, and compaction on a mid-write
  block would remove the rows that did land while leaving the period
  `appending`, so a later `/resume` would reconcile to `landed = ∅` and write
  them again. `compact_block`'s precondition (4.5) refuses that undo outright,
  so the message must not send the user at it first. Otherwise it marks the run abandoned and releases
  the guard. Rows in `split`, `categorised` or `failed` periods are discarded,
  which is the point of cancelling — but discarding is the one destructive
  thing a single slash command can do in a design that deliberately asks for
  no confirmation before *writing*, so `/cancel` **requires `confirm: true`
  when the discard count is non-zero** and names that count in the refusal.
- **An incomplete run must not look finished.** The closing summary and
  `/status` both name every period that is not `written`, with its status, its
  row count and what to do about it.
- Legacy pending or failed items from before the cutover: 4.10 retires them
  before the rebuild, so the pipeline needs no legacy path. `data/` on the Pi
  holds none today (section 11).
- Unparsable `booking_date`: the **row** is dropped and reported with file
  name and row number; the file is still processed.
- `csv_helper.normalize_csv_data` guards `len(row) > 17` before indexing, and
  `load_transactions_from_csv` carries `bank_sequence_no` from column 15.
### 4.8 Discord surface

| Command | Change |
|---|---|
| `/upload` | `attachment` plus optional `attachment2..5`, `force: bool = False`. Rejects non-CSV before saving anything. |
| `/resume [upload_id]` | Continue an unfinished run (4.7); newest open run by default. Never re-splits. |
| `/status` | Every open run, and per period its status, row count, flagged count and the AI guess discarded for each flagged row. **Names every period that is not `written`**, so an incomplete run cannot read as success. |
| `/sort` | Optional `month`; default: every sheet touched by the last run. **Refuses while any run has a period at `appending`** — sorting reorders a block whose positions that run's recovery depends on (4.6). |
| `/cancel [upload_id]` | Abandon an open run. **Refuses while any period is `appending`**, naming it and sequencing the remedies: `/resume` first to reconcile, then `undo_upload.py` to reverse (4.7). Otherwise marks the run abandoned, releases the guard, and reports how many rows in `categorised` or `failed` periods it discarded. Never undoes writes — `scripts/undo_upload.py` does that. |
| `/months` (new) | Lists the index; `/months register <label> <url>` adds a sheet the bot did not create. The index is authoritative (4.4), so this is also how the user recovers from a lost `data/`. |
| `/review`, `/pending`, `/cached`, `/resetsheet` | **Removed.** |

Deleted outright: `src/finance_core/ui/transaction_prompt.py`,
`src/finance_core/ui/discord_notifier.py`,
`src/finance_core/ui/cached_transactions_view.py`,
`src/finance_core/pending_transactions.py`,
`src/finance_core/background_upload.py`,
`src/finance_core/session_management.py` and the `data/sessions/` directory.
`ExpenseCategory.DUMMY_CACHED` and `IncomeCategory.DUMMY_CACHED` go with them.
The `APPROVAL_CHANNEL_ID` config key is retired.

**`apply_categorization_rules` must move first.** It lives at
`transaction_prompt.py:30-79` and is imported by
`categorization_engine.py:123`, so deleting the UI module without moving it
breaks the regex path — the bot's most reliable categoriser. It is pure (`re`
plus the rule tables) and moves verbatim to a new
`src/finance_core/categorization_rules.py`. This is the **first** commit of
Phase 3, before any deletion.

Household rule: `/upload` and `/resume` accept any user in
`MENTION_USER_IDS`, since the two Discord accounts share one budget. With the
per-user views gone this is the only place user identity still matters.

### 4.9 Categorisation and flagging (new section)

`categorization_engine` keeps its two passes (regex, then batch AI with
per-row fallback) and its `CategorizationResult`. What changes is what the
pipeline does with a low-confidence result.

```python
def category_for(result, is_income) -> tuple[str, str, dict | None]:
    """Returns (category, description, discarded_ai_guess)."""
    if result.method in ("regex", "ai_auto"):
        return result.category, full_description(result), None
    placeholder = (IncomeCategory.NOG_IN_TEDELEN if is_income
                   else ExpenseCategory.NOG_IN_TEDELEN).value
    return placeholder, full_description(result) or None, {
        "ai_category": result.category,
        "ai_confidence": result.confidence,
    }
```

- `AI_CONFIDENCE_THRESHOLD` (0.75, hardcoded today as a default argument at
  `categorization_engine.py:383`) becomes a config key. It now decides
  *flag or not*, never *write or not*.
- **Both placeholder categories are withheld from the AI's own option list.**
  `categorization_engine.py:164-167` and `:257-262` build the category
  dictionaries handed to the model as
  `{cat.value: cat.value for cat in ExpenseCategory if cat != ExpenseCategory.DUMMY_CACHED}`
  — the only exclusion is `DUMMY_CACHED`. So `! Nog in te delen !` is already
  an option the model may return *confidently* for expenses today, and adding
  the income member would extend that. A confident placeholder answer takes
  the first branch of `category_for`: the row is written flagged, but with no
  `discarded_ai_guess`, not added to `flagged`, and absent from the flagged
  count — so the one number the user relies on to know how much the run left
  undecided would undercount by exactly the rows the model found hardest. Both
  `NOG_IN_TEDELEN` members are therefore excluded from both dictionaries, by
  the same mechanism `DUMMY_CACHED` uses.
- **Belt and braces**: `category_for` treats an `ai_auto` result whose category
  equals either placeholder as flagged anyway, so the count stays honest even
  if a future edit reintroduces it to the list.
- The description still comes from the AI when it produced one, so a flagged
  row is recognisable. When it did not, `format_transaction_for_sheet`'s
  existing fallback (counterparty plus remittance) applies; the "Unknown
  Transaction" placeholder stays as the last resort.
- The discarded AI guess is written into the run state and into the summary
  embed, one line per flagged row. That is the only place it survives, and it
  is why the user loses nothing by dropping the review UI. Discord caps an
  embed description at 4,096 characters and a message's embeds at 6,000, so
  the summary prints at most `SUMMARY_FLAGGED_LINES` (40) of them and, beyond
  that, attaches the full list as a `.txt` file to the thread message. The run
  state always holds all of them.

Round 9 (2026-09-21, same instance, revision 10): **APPROVE WITH CONCERNS**.
M-W and M-X verified closed against the text rather than against the ledger;
r1-r3 applied. The deferred repeat-trip of the fix-churn breaker explicitly
did **not** fire. One gap was named rather than blocked, because the user had
capped the loop at this round and a precisely scoped gap with its fix written
out was the more useful output than another revision:

**G1 (major, 4.5)** — `compact_block`'s payload type was the last
under-determined value in the design. `read_block` was the only specified
block reader and returns `RowTuple`s, whose amounts carry a **period** decimal
separator, while the workbook is `nl_NL` and `sort_by_date` wrote back
`USER_ENTERED`. The natural implementation would therefore have re-parsed
every amount in a block on a routine end-of-upload sort — the one operation
that touches rows it did not write. Fixed in revision 11 by the reviewer's own
one-clause remedy: `read_block` returns both representations, `compact_block`
takes the raw cells and writes `RAW`, and `RowTuple`s are used for the sort key
and `remove_rows`' matching only. `tests/test_sort.py` gains the assertion.

The reviewer's own closing note on how G1 escaped nine rounds is worth keeping:
the sort was closed as a *sequencing* question in round 1 (M5) and never
re-examined as a *representation* question after `RowTuple` arrived in revision
8. The recurrence moved to the write boundary, which is the last boundary
there was.

**Loop provenance**: 9 rounds total (rounds 1-2 in a previous session that
ended on a spend limit, rounds 3-9 here), including one cold read by a fresh
instance. The fix-churn breaker tripped twice: the first trip produced the
holistic rewrite of 4.5-4.7 plus the cold read; the second was deferred to the
round-8 trajectory checkpoint, where the user chose one final round. Blocking
findings per round: 16, 9, 10, 6, 4, 6, 4, 2, 0-plus-one-named-gap. The plan
exited on APPROVE WITH CONCERNS with G1 fixed afterwards, not on a clean
APPROVED. Section 11 puts the historical flagged
  volume at 3 rows a month, so the cap is a safeguard for a bad AI day on a
  500-row backlog rather than the normal case.
- `ExpenseCategory.NOG_IN_TEDELEN` already exists and is
  `ExpenseCategory.DEFAULT`; it sits at `Summary!B45` in the template and is
  summed like any other expense category, so flagged spend is visible in the
  monthly total rather than hidden.

**`IncomeCategory.NOG_IN_TEDELEN` is new** and needs a home in the sheets.
The formula inspection of 2026-09-21 (section 11) makes this far smaller than
revision 4 assumed:

- `constants.py` gains `NOG_IN_TEDELEN = ("! Nog in te delen !", r"nog|!")` to
  `IncomeCategory`, and `IncomeCategory.DEFAULT` changes from
  `PERSONLIJKE_REKENING` (note the spelling as it exists at
  `constants.py:66`) to it, so an unmatched income row is flagged rather than
  silently filed as a personal-account transfer.
- **The receiving row already works.** `Summary!K35` and `K36` already carry
  `=if(isblank($H35); ""; sumif(Transactions!$J:$J;$H35;Transactions!$H:$H))`,
  guarded by `isblank`, on the template and on every 2026 month checked. The
  income total `K26 = sum(K27:K44)` already covers row 35, and the dropdown
  range `=Summary!$H$27:$I$44` already includes H35. So
  `scripts/add_income_placeholder.py` writes **one text label into `H35`** and
  nothing else: no formula replication, no row insertion, no range extension,
  and no reference shift anywhere. The `isblank` guard is what switches the
  existing `SUMIF` on.
- Expenses need no sheet change at all: `! Nog in te delen !` is already at
  `B45`, its `SUMIF` is at `E45`, and the expense total `E26 = sum(E27:E)` is
  open-ended, so the three flagged rows in `04/2026` are **already** counted
  in that month's expense total. Revision 4 flagged this as possibly a live
  bug; it is not.
- The script still runs `--dry-run` by default, printing per sheet the target
  cell, its current content and the label it would write, and refusing any
  sheet where `H35` is not empty or `K35` does not hold the expected `SUMIF`.
  Because the change is one text cell, the rollback is Drive version history
  or clearing `H35`; the script prints that line.
- The registry's fidelity check (4.4 step 6) no longer merely asserts the
  label exists — it writes a flagged row of a known amount and asserts the
  income and expense totals and `E17` all move by it. That catches a created
  sheet whose totals do not reach the placeholder, which a label-presence
  check cannot.

### 4.10 Configuration, state files, scripts, deployment

Added to `config_settings.py` and the example:

```python
GOOGLE_AUTH_MODE = "oauth"                      # Phases 1-3 only
GOOGLE_OAUTH_CLIENT_PATH = "data/google/oauth_client.json"
GOOGLE_OAUTH_TOKEN_PATH = "data/google/authorized_user.json"
GSHEET_NAME_PATTERN = "Maandelijks Budget {label}"
GSHEET_TEMPLATE_ID = "1OSi4W3B3PrfCTQyxt3OreLmqSs4nXY82Wlg1_eohTs8"
GSHEET_FOLDER_ID = "1QoYs19vu04_DFIszlfWOJP7BoQLEtfaG"
GSHEET_AUTO_CREATE = True
GSHEET_CREATE_NONADJACENT = False               # see 4.4 adjacency guard
GSHEET_DATA_START_ROW = 5                       # replaces the two START_ROW keys
SHEET_INDEX_PATH = "data/sheet_index.json"      # AUTHORITATIVE; back it up
PERIOD_BOUNDARY_MARKERS = [r"\bDUO\b", r"Anamata"]
PERIOD_BOUNDARY_MIN_AMOUNT = 250.0
PERIOD_MIN_DAYS = 20                            # boundary-to-boundary is 27-32 days
PERIOD_MAX_DAYS = 35                            # was 40; see 4.3
PERIOD_STEP_DAYS = 29                           # fallback only, beyond known history
PERIOD_LABEL_SPLIT_DAY = 15
PERIOD_STATE_PATH = "data/period_state.json"
UPLOAD_LEDGER_PATH = "data/upload_ledger.json"
AI_CONFIDENCE_THRESHOLD = 0.75                  # flag or not; never write or not
AI_RUN_MAX_MINUTES = 30                         # re-sized in Phase 2
AI_PER_TX_FALLBACK_LIMIT = 10
AI_BUDGET_TRIP_ACTION = "write_flagged"         # or "stop"; see 4.7
```

Retired: `GSHEET_NAME` (deprecated until Phase 4), `GSHEET_TAB`,
`GSHEET_EXPENSE_START_ROW`, `GSHEET_INCOME_START_ROW`, `APPROVAL_CHANNEL_ID`,
`SESSION_DIR`, `GOOGLE_CREDENTIALS_PATH`. The required-keys self-check runs
first thing in `bot.py`, before any other config import: it
`importlib.import_module("config.config_settings")`s, checks each required
name with `getattr`, prints one line naming the missing keys and exits.
`.gitignore` gains `data/google/`, `data/runs/`, `data/*.json`.

State files, and how each is recovered if `data/` is lost:

| File | Role | Recovery |
|---|---|---|
| `data/google/authorized_user.json` | authoritative | `scripts/google_login.py` on the workstation |
| `data/sheet_index.json` | **authoritative** — the bot has no Drive read scope, so it cannot be rebuilt by listing | re-seed from the ids in section 11, plus `/months register` for anything newer; `/months` prints the current index so the user can keep a copy; include `data/` in the Pi backup set |
| `data/period_state.json` | rebuildable | `scripts/seed_state.py` |
| `data/upload_ledger.json` | rebuildable (weak keys) | `scripts/seed_state.py`; strong keys and audit are lost, which only weakens dedup for rows written after the last seed |
| `data/runs/` | **holds unwritten rows** (4.7) while any period is not `written`; transient once a run is complete | none needed, but do not delete mid-run — losing it loses the rows a failed period still owes |
| `failed_uploads.json` | transient | none needed |

`run.sh --force-rebuild` runs `docker system prune --volumes`; `data/` is a
bind mount, not a volume, so it survives, and the plan says so where the
flag is documented.

Deployment facts that drive Phase 4:

- the `Dockerfile` does `COPY src/ ./src/`, so the Pi's gitignored
  `src/config/config_settings.py` ships **inside the image**;
- `run.sh:51-55` **exits 1** when `src/config/config_settings.py` is missing;
  `run.sh:57-60` only prints a warning and continues when
  `src/config/google_service_account.json` is missing. Revision 4 said it
  refuses; it does not. So deleting the key file does not block startup, and
  the `run.sh` change in Phase 4 step 2 is desirable rather than unblocking;
- `run.sh:131` runs `docker system prune -f --volumes` on `--force-rebuild`,
  which can remove the previous image and with it the rollback.

Phase 4 therefore edits the Pi's config before the rebuild, tags and keeps the
running image first, changes `run.sh` to check the token file instead of the
key, and bind-mounts `src/config` read-only so a future setting change needs
no rebuild.

Scripts:

| Script | Change |
|---|---|
| `scripts/google_login.py` | new (4.2) |
| `scripts/add_income_placeholder.py` | new (4.9), one-off, dry-run by default; writes one label cell per sheet |
| `scripts/seed_state.py` | new: reads each indexed, populated sheet (date, abs amount, block; no descriptions) into the weak ledger; seeds `Anchor.history` from the **earliest row date** of each sheet, which is that month's boundary by construction (4.3); prints the anchor and the full history and requires the user to confirm both; `--set-anchor DD-MM-YYYY MM/YYYY` |
| `scripts/undo_upload.py` | new (4.6), Phase 1 |
| `scripts/retry_failed_transactions.py` | uses `sheet_registry` + `sheet_writer`, groups by `period_label`; loses its `pending_transactions` import |
| `scripts/recategorize_pending.py` | **deleted** — it exists only to re-run AI over the pending approval queue, which no longer exists |
| `scripts/sheet_shape.py` | keeps the service account (now folder-wide) for inspection; gains a `--folder` listing and a **`--summary` mode** that prints the `Summary` tab's total and `SUMIF` formulas, so section 11's facts are re-derivable from a committed tool rather than from one-off spike scripts |
| `scripts/make_fixture.py` | renumbers column 15 uniquely instead of zeroing it; can duplicate a chosen row to exercise the multiset path |
| `scripts/register_sheets.py` | new after all: seeds `data/sheet_index.json` from a pasted list, or from the ids recorded in section 11. Needed because the index is authoritative (4.4) and there is no Drive listing to rebuild it |
| `scripts/test_batch_categorization.py` | unchanged |

## 5. Tests first

`pytest.ini`: `testpaths = tests`, `pythonpath = src`, `asyncio_mode = auto`.
`requirements-dev.txt` with `pytest`, `pytest-asyncio`; CI installs it and
its matrix becomes 3.12 only (the code already uses `X | None` at runtime and
the Pi image is 3.12). `archive/old_browsercode_scripts/test_browsercode_login.py`
currently aborts collection and is excluded. Fixtures:
`tests/fixtures/multi_month.csv` (user's anonymised export, three or more
boundaries) and hand-written `tests/fixtures/edge_cases.csv`. Fakes:
`FakeWorksheet` (`get`, `update`, `resize`, `row_count`, `batch_clear`),
`FakeSheetsApi` (`create` recording properties, `copyTo`, `batchUpdate`),
`FakeDrive` (`list`, `update`, `delete`), `FakeAI`.

`tests/test_periods.py`

- DUO 24-03 then salary 25-03 → one boundary, `04/2026`.
- Three candidates 24, 25 and 43 days after a boundary → the third opens a
  new cluster (measured from the cluster boundary, not chained).
- Boundary day 14 → same month; day 15 → next month.
- Leading rows with anchor inside the window → anchor label; 60-day overlap
  reaching one step before the anchor → previous label, no error; two steps
  → error, and with `force` the step rule labels them; without anchor →
  previous label with warning; December ↔ January rollover both ways.
- Marker-less export 16-04 to 20-04 with anchor (24-03, `04/2026`) →
  `04/2026`; same export without anchor → `05/2026` plus warning.
- Marker-less export beyond `anchor.boundary + max_days` → error, and still
  an error with `force`.
- DUO `DBIT` and "Salaris Janneke" from a private person → not candidates.
- Bonus above `min_amount` on 10-12 after a `12/2026` period → error listing
  both boundaries; with `force` labels unchanged.
- January plus March with February missing → error; with `force` March lands
  in `04/2026` and the summary names `03/2026` as skipped.
- Leading remainder of 5 days and final open period of 3 days → no error
  (exemption); a closed period of 12 days → error.
- Overlapping export whose first candidate is the anchor's own boundary → no
  new period.
- Rows on the boundary date listed before the DUO row → new period.
- Count in equals count out; every row has `period_label`.
- **The real 2026 spans** (section 11) replayed as a regression case: an
  anchor of `(24-04-2026, "05/2026")` plus a 22-05 to 21-09 export yields
  `05/2026` (leading), then `06/2026` … `09/2026`, with no error.
- **The constant edges that revision 4 got wrong.** A row 31 days before the
  anchor boundary, with a real 31-day previous period in `history`, gets the
  previous label and does **not** abort (revision 4's 30-day step made this
  two steps and aborted the run). A row 32 days after the anchor boundary is
  **not** given `anchor.label` (revision 4's `max_days = 40` silently
  swallowed rows 32-39 that belong to the next month). A row older than the
  oldest entry in `history` falls back to the 29-day step rule, and two steps
  back still aborts without `force`.
- A 60-day overlapping export spanning the real 31-day `04/2026` period
  labels every row correctly with no error.

`tests/test_ledger.py`: identical rows → multiset count, both written on
first upload, none on re-upload; strong hit across labels skipped; weak match
only against seeded labels; cross-label skip reported separately; written rows
recorded as content; `runs[upload_id]` carries `anchor_before`; **no pending
state exists** (a row is either recorded or not).

`collapse_within_upload`: **two attachments overlapping by a month, one of
which also contains a genuine same-day duplicate pair, write each real
transaction exactly once and the duplicate pair as two rows** — the maximum
rule, not the sum; a single file is unchanged by the collapse; collapsed
duplicates are counted separately from ledger skips in the summary; with
`bank_sequence_no` in the strong key the same fixture gives the same answer.

`tests/test_sheet_registry.py`: index hit opens by key and verifies the header
row; a stale id raising `SpreadsheetNotFound` is its own error and never a
silent re-create; index miss with auto-create off → `MissingSheetError`; **a miss for a
non-adjacent label raises rather than creating, even with auto-create on**
(index newest `06/2026`, `resolve("09/2026")` raises), and
`GSHEET_CREATE_NONADJACENT = True` permits it; **adjacency is chronological,
not lexicographic** — an index holding `11/2026`, `12/2026` and `01/2027`
makes `resolve("02/2027")` adjacent, where a string maximum would refuse it;
the backlog sequence works, index newest `06/2026` creating `07`, then `08`
adjacent to `07`, then `09` adjacent to `08`; **`create`'s starting-balance
step uses `lookup` and never creates** — creating `09/2026` with
`GSHEET_CREATE_NONADJACENT = True` against an index topping out at `06/2026`
creates **exactly one** sheet and lists `09/2026` under "set the starting
balance"; nothing is written to the index when the fidelity check fails;
create passes the template's `locale`, `timeZone`, `autoRecalc`; copy order is
Transactions, rename, Summary, rename, delete `Sheet1`, reorder; **`addParents`
403 leaves the run succeeding with the sheet in root, its id in the index, and
the month named in the summary**; fidelity failure → delete +
`SheetLayoutError`; **the fidelity check fails when a flagged row does not
move the totals** — a fake whose income total range stops short of the
placeholder row must be rejected, which the old label-presence assertion
passed; `L8` set from the previous month's `E17` when it is in the index,
non-empty, and either `written` in this run or untouched by it; **creating
month N while month N-1 is at `appending` writes no `L8` and lists N under
"set the starting balance"**, which a "not `failed`" precondition would have
got wrong, since `appending` never becomes `failed`; `with_retry` retries 429 and 503 three times
and not 400, **and is not applied to `values_update`**.

`tests/test_sheet_writer.py`: **`canonical()` is total** — a date serial, a
text `DD-MM-YYYY` date and an ISO string all canonicalise to the same ISO
date; an `int` and a `float` amount both canonicalise to the same 2-decimal
string; and a genuinely unconvertible value carries through as
`str(v).strip()` **without raising**, so `plan_append` over a block modelled
on `02/2026`'s 70 text-typed date cells returns a stable digest twice in a
row; `canonical` is not applied to `read_block`'s output, which is already
canonical; **`canonical()` is the only producer of a `RowTuple`** — the round-trip that fakes cannot prove
is asserted against the real API in Phase 1 instead (4.5); `read_block` is
**positional**, so a block with an internal blank row round-trips with index
*i* equal to sheet row `START + i`, and the positional reconcile path is taken
rather than the fallback; a write that mutates and then raises 503 ends with
the rows present **exactly once** (no blind retry); `plan_append` records both
`first_write_row` and the `prefix` baseline before any write;
**`commit_append` recomputes its own append point and takes no baseline**, so
appending to a block that moved since `plan_append` lands after its current
last row; next free row from the column, not config; empty sheet starts at row
5; a sheet the old per-row path partly filled appends after its last row (the
`05/2026` case: expenses resume at 104, income at 12); blocks independent;
capacity expanded before write; concurrent appends to one sheet do not
overlap; failure writes `failed_uploads.json` with label and upload id;
returns the `(key, RowTuple)` pairs written, which are the audit's input;
**no sort inside append**; `remove_rows` skips a tuple it cannot find, returns
`(removed, not_found)`, never removes more occurrences of a tuple than it was
passed, and compacts; **`sort_by_date` refuses for a spreadsheet with an
`appending` period**.

`tests/test_sort.py`: **a sort writes back the raw cell values, not
`RowTuple`s** — the fake asserts `compact_block` received date serials and
numeric amounts and was called with `RAW`, so a period-decimal string can
never reach an `nl_NL` workbook; **an amount is byte-identical before and
after a sort** on a block the bot did not write; offset 5 (headers untouched);
row count preserved;
**blank row inside the block compacted with no stale tail** (the current
bug); single row; income and expense blocks independent; an amount survives
the `USER_ENTERED` round-trip under the `nl_NL` locale (fake worksheet models
the locale parse).

`tests/test_flagging.py` (new, replaces `test_review_flow.py`):
`method='regex'` and `ai_auto` keep their category; `ai_manual_needed` and
`none` get `! Nog in te delen !` for the right block; an income row gets
`IncomeCategory.NOG_IN_TEDELEN`, not `Persoonlijke rekening`; the AI
description survives onto a flagged row; a result with no description at all
falls back to counterparty plus remittance; the discarded AI guess is recorded
in the run state and appears in the summary; the threshold is read from config
and a row exactly at the threshold is not flagged; **no code path holds a row
back from the sheet**; **the category dictionaries handed to the AI contain
neither placeholder**; **an `ai_auto` result whose category is the placeholder
is still counted as flagged**, so the flagged count in the summary equals the
number of placeholder rows in the sheet.

`tests/test_undo.py`: on a sheet with 100 pre-existing rows, append 20,
sort, undo → block identical to its pre-run content; anchor restored,
including its `history`; **a run that crashed between `record_written` and
`commit_append` undoes to a no-op**, because the audit is written after the
write and so never named those rows; **undo on a block containing a
pre-existing row equal to a recorded tuple does not remove it** beyond the
recorded multiplicity; `not_found` is reported rather than raising;
`--drop-created` removes the index entries whose `created_by_bot` is true for
that `upload_id`, and nothing else; **`remove_rows` refuses for a spreadsheet
with an `appending` period** (inherited from `compact_block`), and
`/cancel`'s refusal message names `/resume` before `undo_upload.py`.

`tests/test_reconcile.py` (new): an `appending` period whose block already
contains a 4-tuple identical to an intended row **placed last in the block**,
with the append not landed, writes the intended row — that placement is the
only one that distinguishes a `first_write_row` baseline from a last-used-row
baseline, and the wrong reading silently drops the row; two intended identical
rows both land; a period where the expense block landed and the income block
did not appends only the income rows; **a write that raises after the expense
block landed leaves the period `appending`, and `/resume` writes only the
income rows** (the pipeline-level counterpart to the writer's 503 test);
reconciliation on an
empty block uses `GSHEET_DATA_START_ROW`; after reconciliation
`record_written` covers every intended row exactly once.

The commit-order and change-detection cases, which are what the append
contract in 4.6 exists to pin down:

- **crash between `record_written` and the `written` flip** → the period is
  still `appending`, `/resume` reconciles to `landed == intended`, appends
  nothing, re-records idempotently, and a subsequent overlapping upload of the
  same range writes **zero** rows. No test setup can produce a `written`
  period with no ledger entry, because recording precedes the flip.
- **crash between the baseline write and `record_written`** → over-recorded
  ledger, reconciliation finds `landed == ∅`, appends everything, no
  duplication.
- **`compact_block` between crash and resume** → the **prefix digest** check
  fails and the content fallback runs. The test asserts **which branch ran**,
  not merely that no row was lost: a row-count check would pass here, because
  compaction preserves the non-empty count, and the positional shortcut would
  be taken silently.
- **the fallback's known weakness is characterised rather than hidden**: a
  pre-existing row whose tuple equals an intended row causes that intended row
  to be dropped as already-present, and the summary reports that the fallback
  ran so the user can compare the period's row count against the sheet.
- **the fallback does not overwrite live data**: a block sorted between crash
  and resume, with `remaining` non-empty, appends after the block's *current*
  last row and leaves every pre-existing row present — the case a stale
  `first_write_row` used as a write position would have destroyed.
- **the reconcile branches partition indices**: a period with two identical
  intended rows of which exactly one landed writes **one** row, audits
  **two**, and satisfies `len(found_idx) + len(remaining_idx) == len(intended)`;
  undoing that run removes exactly two occurrences. A membership test instead
  of multiplicity-respecting consumption fails this case, and nothing maps a
  `RowTuple` back to a transaction anywhere in the implementation.
- **reconciliation writes the ledger from transactions, not `RowTuple`s**: the
  strong keys a reconcile records are byte-identical to those a first-attempt
  commit of the same period records. A `RowTuple`-derived key is impossible to
  produce, so this test fails loudly if the wrong value is in scope.
- **crash between `commit_append` and `record_audit`** → `/resume` reconciles
  to `remaining = ∅` but audits the `found` rows, so a subsequent
  `undo_upload.py` returns the block to its pre-run content with
  `not_found == 0`. Without the `found` term the audit stays empty and undo
  silently reverses only part of the run.
- **the fallback path audits only what it appended**, and the summary reports
  partial undo coverage for that period.

`tests/test_process_upload.py` (fakes): fixture with three boundaries → four
sheets, per-sheet counts equal the splitter's, and **rows written equals rows
accepted**; second identical upload writes zero; one period's `copyTo`
refused → that period `failed`, the others written, **and the failed period's
rows are still in the run state**, so a `/resume` after the cause is fixed
writes them and the total written across the two runs equals the total
accepted; the uploaded files survive until every period is `written`;
**`GoogleAuthError` mid-run stops the run, leaves every un-started period at
`split` with its rows in the run state, and a later `/resume` writes them, so
rows written across both runs equals rows accepted**;
`AI_BUDGET_TRIP_ACTION="write_flagged"` writes the remainder flagged and
`"stop"` leaves it `categorised` and reports; `/resume` on an `appending`
period reconciles and writes only the missing rows, and writes nothing when
the append had in fact landed; `/resume` on a `categorised` period re-resolves
without re-splitting; `/resume` with two open runs picks the newest and honours
an explicit `upload_id`; **`/cancel` refuses while a period is `appending`**, requires `confirm: true`
when the discard count is non-zero, and reports that count; **`/sort` refuses
while a period is `appending`**; **`/upload` refuses while any open run has a
period at `appending`**, naming it; **a write failure leaves the period
`appending`, the run continues, and the closing sort skips that sheet only**,
so `/resume` takes the positional path rather than the fallback; **the
tripping period finishes under `write_flagged` semantics even when
`AI_BUDGET_TRIP_ACTION = "stop"`**, so no row is written without a category; a second `/upload` during a run
is refused; **a run whose `periods` list is empty (a crash before the split)
is re-run from the start by `/resume` and never reported as success**; unparsable date drops the row and reports it; the summary and
`/status` both name every period that is not `written`; summary lists every
period, boundaries, created sheets, skipped duplicates, collapsed intra-upload
duplicates, skipped months and flagged counts.

`tests/test_csv_multi.py`: five files preserve rows and sort order; sequence
number carried; a row with fewer than 18 columns is skipped **and
`normalize_csv_data` does not raise on it** (today it indexes `row[17]`
unguarded); non-CSV attachment rejected before saving.

`tests/test_categorization_rules.py` (new): the rules moved out of
`transaction_prompt.py` behave identically — a `{c}` capture-group
substitution, a no-capture template, income versus expense rule selection, and
no match returning `(None, None)`. Plus the fact that drives 4.3's seeding
choice: a `DUO Hoofdrekening` row yields the description `"Duo uitkering"` and
an Anamata salary yields `"Salaris Ezra"`, and **neither
`PERIOD_BOUNDARY_MARKERS` pattern matches either string** — so nothing may
marker-match a sheet's Description column.

`tests/test_seed_state.py` (new): `history` seeded from the five populated
2026 sheets reproduces 24-12-2025, 23-01, 24-02, 23-03 and 24-04 with their
labels, taking the earliest date across both blocks; the stray 23-03-2026 row
in `02/2026` does not disturb its boundary, because the boundary is the
earliest date, not the latest; rule 4 places a row inside each real interval
correctly from that history; a sheet with no rows is skipped, not seeded with a
null boundary; the weak ledger is seeded with date, absolute amount and block
only, never descriptions.

`tests/test_add_income_placeholder.py` (new): a clean sheet is patched at
`Summary!H35` and nothing else is written; a sheet whose `H35` is non-empty is
refused; a sheet whose `K35` is not the expected guarded `SUMIF` is refused;
`--dry-run` is the default and writes nothing.

`tests/test_google_auth.py`: missing token → error naming the login script;
`RefreshError` → same class; refreshed credentials are written back; **scopes
are exactly `spreadsheets` + `drive.file`, and the test fails if any
`drive.*` scope beyond `drive.file` is requested** — a guard against a future
edit quietly reintroducing a restricted scope; `service_account` mode still
builds a client during the transition.

## 6. Order of work

Every phase ends with tests green and a commit via the commit handler.
Phase 1 is **blocked** on the user's OAuth client (Phase 0). Phase 2 needs
nothing from Phase 1 and can run in parallel with it.

**Phase 0, pre-work**

- Done 2026-09-20: repo synced (local = Pi = origin at `ef0c95c`, stale WIP
  stashed), venv rebuilt on 3.12, `scripts/sheet_shape.py`,
  `scripts/make_fixture.py`, spike proving the service account cannot copy,
  template properties and cell formats read.
- Done 2026-09-21: service-account capability re-verified after folder
  sharing (still cannot create); all 31 sheet ids, the folder id and the
  template id collected; six months of real spans read and the boundary rule
  validated; the income category table confirmed to lack a placeholder; the
  code inspection in section 11.
- Done 2026-09-24 (me): branch `feat/multi-month-upload`; `pytest.ini`;
  `requirements-dev.txt`; CI fix (paths moved to `src/config/`, matrix 3.12,
  `pytest` step, archive test excluded by `testpaths`); fixture script
  renumbers column 15 through a fixed bijection (unique, stable across runs)
  and gains `--duplicate-row N`; `csv_helper` carries `bank_sequence_no` and
  guards `row[17]`; `scripts/add_income_placeholder.py` written and dry-run
  against all seven targets, every one `would-write`;
  `scripts/register_sheets.py` (`seed` / `add` / `paste` / `list`) on a new
  pure module `finance_core/sheet_index.py` that `sheet_registry` will reuse;
  `data/sheet_index.json` seeded with the six 2026 ids of section 11;
  `.gitignore` gains `data/google/`, `data/runs/`, `data/*.json` and
  un-ignores `tests/fixtures/*.csv`. 91 tests green.
- User steps below, written out click by click with a status checklist:
  `docs/plans/PHASE0_USER_SETUP.md`.
- User: review the `add_income_placeholder.py` dry-run output, then run it
  with `--apply` on the template and the six 2026 months. `06/2026` is
  included although it is empty: it was copied from the template before the
  label existed, and it is the first month the backlog writes into. One text
  cell per sheet (`Summary!H35`); the receiving `SUMIF` and the total already
  exist (4.9), so nothing else changes.
- User: Google Cloud project `asnexport` → OAuth consent screen: External,
  scopes **`spreadsheets` and `drive.file` only** — if the console offers to
  add any other `drive.*` scope, decline it; they are restricted and cost a
  CASA audit (4.2) — **publish to production** → Credentials → OAuth client,
  Desktop app → JSON to `data/google/oauth_client.json`. Confirm the consent
  screen shows the "unverified" warning and not "access blocked"; if blocked,
  4.2 plan B is decided here.
- User: export one overlapping day twice from ASN and compare column 15 for
  the same transactions (5 minutes); the result decides whether the sequence
  number joins the strong key (4.6).
- User: run `scripts/make_fixture.py` on a real export spanning at least
  three boundaries, check `sheet_shape.py csv` on the output, commit
  `tests/fixtures/multi_month.csv`.

**Phase 1, Google layer**: `google_auth.py`, `google_login.py`,
`sheet_registry.py`, `sheet_writer.py` (append, read_block, compact, sort,
remove), `ledger.py`, `undo_upload.py`, `with_retry`, the `google_sheets.py`
import change and the deletion of its dead clear-and-rewrite pair, and their
tests. First action in the sandbox: `create` a test month from the template and
run the 4.4 step 6 fidelity check in full — including the **behavioural totals
assertion** (write a flagged expense row and a flagged income row of a known
amount, assert `E26`, `K26` and `E17` each move by it, then remove them and
assert the totals return), not merely that the placeholder labels exist —
because this decides plan A versus plan B before anything else is built on it. Then write,
sort, undo, delete.

**Phase 2, periods**: `periods.py`, config keys, tests, fixture-driven;
confirm the backlog walk of 4.3 against the fixture; time one 40-row AI chunk
on the Pi and set `AI_RUN_MAX_MINUTES` from it.

**Phase 3, pipeline and UI**, in this order:

1. Move `apply_categorization_rules` to `finance_core/categorization_rules.py`,
   repoint `categorization_engine.py`, add `tests/test_categorization_rules.py`.
   Commit. Nothing is deleted yet.
2. `constants.py`: add `IncomeCategory.NOG_IN_TEDELEN` and change its
   `DEFAULT`. **Do not touch `DUMMY_CACHED` yet** —
   `transaction_prompt.py:14-19` reads both members inside a
   `try/except ImportError`, which does not catch the `AttributeError` that
   removing them would raise, so the module would break while it is still
   imported. Their removal moves to step 5, the deletion commit.
   `AI_CONFIDENCE_THRESHOLD` from config; exclude both placeholders from the
   AI category dictionaries at `categorization_engine.py:164-167` and
   `:257-262`. Add the flagging logic of 4.9 and `tests/test_flagging.py`.
3. `export.py` rewritten to `process_upload`, run state, in-flight guard,
   resume reconciliation.
4. `bot_commands.py` and `bot.py`: new command surface, config self-check,
   `start_upload_queue` and both persistent-view registrations removed.
5. One commit deletes `transaction_prompt.py`, `discord_notifier.py`,
   `cached_transactions_view.py`, `pending_transactions.py`,
   `background_upload.py`, `session_management.py` and `data/sessions/`, **and
   in the same commit drops both `DUMMY_CACHED` members** now that nothing
   reads them. Exit check:
   `grep -rn "background_upload\|pending_transactions\|transaction_prompt\|session_management\|DUMMY_CACHED" src` is empty.

**Phase 4, tools, docs, cutover** (in this order)

1. `retry_failed_transactions.py` on the new layer; delete
   `recategorize_pending.py`; `sheet_shape.py --folder`; `seed_state.py`.
   Exit check: the same grep over `scripts` is empty.
2. Docs: `AGENTS.md`, `docs/DEVELOPMENT.md`, `docs/CHANGES.md`,
   `config_settings.example.py`; `run.sh` (token check, `src/config` bind
   mount, remove the service-account check, note on `--force-rebuild`);
   `Dockerfile` unchanged.
3. On the Pi, before the rebuild: **tag and keep the running image**
   (`docker tag <current> finance-bot:pre-multimonth`) so `--force-rebuild`'s
   `docker system prune -f --volumes` at `run.sh:131` cannot destroy the
   rollback; pull the branch; edit `src/config/config_settings.py` with the
   block from 4.10; `scp` the token and client JSON plus the seeded
   `sheet_index.json` to `data/` (owner `pi`, `0600` for the credentials);
   confirm `data/` holds no live pending or cached items and the live sheets
   no `CACHED` rows (`sheet_shape.py` category counts).
   `seed_state.py` needs the new modules and the OAuth token and the Pi has no
   host venv for the bot, so it runs **inside the newly built image** —
   `docker run --rm -v <data>:/app/data <new-image> python scripts/seed_state.py`
   — after the build in step 4 but before the service is switched over. Its
   printed anchor and `history` must be confirmed by the user.
4. Build, run `seed_state.py` per step 3, then start; the self-check must
   pass; `/months` must list every **2026** month (2024 and 2025 live in
   subfolders and are out of scope, section 11).
5. Backlog run from Discord with the user watching the thread: one export
   from **22-05-2026** to today. The summary must show the `05/2026` leading
   remainder, every created month, and the flagged count.
6. Remove `GOOGLE_AUTH_MODE`, `GSHEET_NAME`, `GOOGLE_CREDENTIALS_PATH` and
   the key file from the bot's config; final commit; `/docs-update` for the
   homelab docs (Finance Bot section: `data/` in the backup set, the review
   UI is gone, follow-up is the `! Nog in te delen !` filter).

## 7. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| A hand-edited text-typed cell in a live sheet breaks the append | was certain for `02/2026` | `canonical` is total: an unconvertible value carries through as `str(value).strip()`, and a text `DD-MM-YYYY` date canonicalises to the same ISO string as the serial the bot writes (4.5). Measured: 70 such cells exist today (section 11). |
| A wrong AI category below the threshold is now written into the sheet instead of reviewed | certain by design | It is written flagged, so it is never silently wrong: the row carries `! Nog in te delen !`, is summed under that line, and is filterable. The discarded AI guess is in the run summary, and `undo_upload.py` reverses a whole run. |
| A restricted `drive.*` scope is added later, by a future edit or a console suggestion | low | Not requested at all (4.2); `tests/test_google_auth.py` fails if any `drive.*` scope beyond `drive.file` appears; Phase 0 tells the user to decline the console's offer. |
| OAuth consent requires verification even for `spreadsheets` + `drive.file` | low | Phase 0 gate before any code depends on it; plan B (4.2) is the service account for existing months plus hand-created new ones, needing no new scope. |
| The bot creates a duplicate sheet for a month the user made by hand and did not register | medium | Accepted with the 2026-09-21 index decision. Every creation is named in the summary, `created_by_bot` distinguishes the two afterwards, `/months` prints the index, and `undo_upload.py` reverses the writes. The intended workflow is that the bot creates every month. |
| `sheet_index.json` lost with `data/` | low | It is authoritative and cannot be rebuilt by listing, so: `data/` is in the Pi backup set, `/months` prints it on demand, and `register_sheets.py` re-seeds from the ids in section 11. |
| Token expires because the app stays in Testing | medium | Phase 0 checklist; login script prints the reminder; failure surfaces as one Discord error and stops the run. |
| Sheets-API clone loses formulas, validation or locale | medium | Fixed copy order, properties copied from the template, fidelity check with orphan deletion, first action of Phase 1; plan B otherwise. |
| Income flagged into a category no `SUMIF` sees | was certain, now resolved | `K35` already holds the guarded `SUMIF` and `K26 = sum(K27:K44)` already covers it (section 11), so one label in `H35` is enough; the registry fidelity check asserts a flagged row actually moves the totals, not merely that the label exists. |
| Flagged expenses missing from today's totals | investigated, not real | `E26 = sum(E27:E)` is open-ended, so `04/2026`'s three flagged rows are already counted. |
| `add_income_placeholder.py` damages a live Summary tab | very low | One text cell per sheet, no insert, no formula or range change; refuses if `H35` is non-empty or `K35` is not the expected `SUMIF`; dry-run is the default. |
| A spurious marker splits a month | low | Confirmed low: Anamata batches all income into the salary payment. Amount floor, clustering, contiguity abort, `force` for the deliberate case, `undo_upload.py` for the mistaken one. |
| Marker-less mid-cycle export mislabelled | was certain | Anchor state (4.3 rules 4 and 5). |
| Overlapping export aborts instead of skipping | was certain | Ledger runs before the split; step rule for older rows. |
| Historical seam `05/2026` ↔ `06/2026` | low | `05/2026` ends 21-05-2026 and the backlog starts 22-05-2026, so the seam is two days and no boundary sits in it. The seeded weak ledger covers a wider re-export. |
| `05/2026` partly filled by the old per-row path | certain | Writer appends after the last used row (104 / 12); seeded ledger skips its 106 rows. |
| Crash between append and ledger record | medium | Run-state `appending` plus read-back reconciliation on `/resume` (4.6, 4.7). |
| Undo clears rows the sort moved | was certain | Content-addressed audit, written after the write and including rows reconciliation *found*; undo tested after a sort on a partly filled sheet. Partial coverage remains only for a period whose reconciliation took the content fallback, and the summary names it (4.6). |
| Pi config not updated before rebuild | was certain | Phase 4 step 3, config self-check, config bind mount. |
| Deleting the UI modules breaks the regex path | certain if unsequenced | Phase 3 step 1 moves `apply_categorization_rules` out first, with its own test and commit. |
| Long AI run, container restart | medium | Run state per period, `/resume` with reconciliation, AI budget sized from a measured chunk, thread progress. |
| A period fails at resolution and its rows are lost | was certain | The run state holds the categorised rows until the period is `written` (4.7); `failed` is a resumable state; the upload files survive until every period is written; `/status` and the summary name every unwritten period. |
| A non-idempotent write is retried and lands twice | was certain | `with_retry` never wraps `values_update` (4.4); write failures go through the same multiset reconciliation as a crash (4.6). |
| Two overlapping attachments in one `/upload` write the overlap twice | was certain | `collapse_within_upload` before `filter_new`, per-file counts combined by maximum (4.6). |
| Reconciliation drops a row identical to one already in the block | was certain | Multiset subtraction against a recorded pre-append baseline, per block (4.6). |
| The AI confidently answers `! Nog in te delen !` and the flagged count under-reports | was certain | Both placeholders withheld from the AI's option list, and an `ai_auto` placeholder result is counted as flagged anyway (4.9). |
| Pre-anchor rows mislabelled or the run aborted by a fixed step length | was certain | `anchor.history` places rows by real intervals; the step rule applies only beyond known history; constants re-derived from section 11 (4.3). |
| `--force-rebuild` destroys the rollback image | medium | Phase 4 step 3 tags and keeps the running image before the rebuild. |
| Identical legitimate rows dropped as duplicates | low | Multiset ledger; sequence number only if verified stable. |
| Two household accounts | existing | `MENTION_USER_IDS` check on `/upload` and `/resume`. |

## 8. Out of scope

- The bank scraper, FastAPI endpoints and n8n path (still paused).
- Changing categories or AI prompts, beyond adding the income placeholder.
- Planned amounts on new sheets beyond what the template carries.
- Moving already-written rows between sheets (undo plus re-upload covers it).
- The one stray 23-03-2026 row sitting in the `02/2026` sheet, and the
  `abonnementen` / `Abonnementen` capitalisation difference between the
  template and `04/2026` (section 11). Both are pre-existing and harmless.
- Re-reading the sheet to notice that the user has since fixed a flagged
  category by hand. The bot never revisits a written row.
- The 2024 and 2025 months in their subfolders. The index covers 2026 onward;
  the older sheets are readable by the inspection scripts but the bot never
  resolves or writes to them.
- Per-period undo. `undo_upload.py` reverses a whole run, which is the unit
  the write audit records. A single mis-flagged period is corrected by fixing
  the category in the sheet.

## 9. Assumptions to confirm during review

- Up to five attachments per `/upload` is enough.
- `Test Automation Sheet` is retired; the sandbox is a template copy in the
  user's Drive.
- The `Financiën` folder is a normal My Drive folder, not a Shared Drive
  (consistent with the service account seeing `ownedByMe: false` and a
  non-null parent chain).
- `PERIOD_BOUNDARY_MIN_AMOUNT = 250` is below every DUO payment.
- The income category table's first free row is H35 and `K35` holds the
  guarded `SUMIF` on **every** populated 2026 month. Verified on the template,
  `04/2026` and `05/2026`; the script checks the remaining three itself and
  refuses any sheet that differs.
- `addParents` into `Financiën` under `drive.file`: unknown until Phase 1.
  The plan works either way (4.4 step 5); only folder tidiness depends on it.
- The 27-32 day boundary-to-boundary range holds going forward. Rule 7's
  contiguity check is the backstop if it does not.
- No two attachments in one `/upload` are each truncated part-way through the
  same calendar day by an ASN export row cap. `collapse_within_upload`'s
  maximum rule (4.6) is correct for every other overlap shape, but two files
  that each cut mid-day could each hold a different subset of that day's
  identical rows, and the maximum would under-count. If ASN turns out to cap
  export rows, dedup on `bank_sequence_no` instead.

## 10. Scrutiny log

Round 1 (2026-09-20): NEEDS REWORK, 5 critical, 11 major, 10 minor. C1 → 4.3
anchor; C2 → 4.3 rules 1/2/7, `force`; C3 → 4.6 weak ledger, `seed_state.py`;
C4 → 4.10 deployment facts, Phase 4 steps; C5 → 4.4 explicit index, light
scopes; M1-M11, m1-m10 → sections 4.5-4.10, 5, 6.

Round 2: NEEDS REWORK, 1 critical, 8 major, 12 minor. K1 → 4.5 `remove_rows`
plus content-addressed audit in 4.6, `test_undo.py`; J1 → 4.4 step 1
(template properties, verified `nl_NL`); J2 → 4.4 steps 2-4 copy order and
fidelity check; J3 → 4.1 ledger before split, 4.3 rule 4 step rule; J4 →
single definition of `force`, rules 5 and 7; J5 → rule 7 exemptions and
`kind`; J6 → `release` on every discard path; J7 →
`filter_new(current_upload_id)`, review path promotes; J8 → Phase 0 sequence
number check, multiset primary; n1 → `seed_state.py` confirmation; n2 →
anchor advances on accepted periods; n3 → rule 2 wording; n4 → 4.4 step 7;
n5 → self-check via `getattr`; n6 → grep scoped per phase; n7 → undo in
Phase 1; n8 → `upload_id` on the dict; n9 → per-row date policy; n10 → chunk
timing in Phase 2; n11 → section 5; n12 → state-file table and recovery.

Round 2 also endorsed the architecture explicitly ("I am not asking for it to
change again") and noted that the design carries several JSON state stores
with no transaction across them, but that none of them decides where a row
goes on a sheet — "that is now read from the sheet itself each time, which
was the actual disease". Revision 4 reduced those stores further: the session
file is gone and the ledger has no pending state. (Revision 4 also made the
sheet index a cache; revision 5 reverted that to authoritative when the scope
it depended on turned out to be restricted — see the supersession in section
2.)

**Round 2 findings that revision 4 dissolves rather than fixes**: J6 and J7
(pending release and self-skip) and round 1's M2, because there is no pending
state; round 1's R1-Q7 (review volume for a five-month backlog), because
there is no review.

Revision 3 addressed K1, J1-J8 and n1-n12 but was never reviewed — the
session ended at the moment it was written. Revision 4 carries those fixes
forward and adds the 2026-09-21 decisions, so **round 3 reviewed revision 4 as
a whole**, not a delta.

Round 3 (2026-09-21, fresh instance, revision 4 reviewed whole): NEEDS
REWORK, 2 critical, 8 major, 13 minor. No FIX-CHURN; the tunnel-vision check
endorsed the direction again ("I am not asking for the architecture to
change") and confirmed the J6/J7/M2 dissolution as legitimate rather than
evasive. C-A → 4.7 run state holds rows, `failed` resumable, `/cancel`
refuses while `appending`, upload files retained, `/status` names unwritten
periods; C-B → **settled empirically**, see the formula table below: both
totals already cover their placeholder row, so 4.9 shrinks to one label cell
and the fidelity check becomes behavioural; M-A → 4.6
`collapse_within_upload`; M-B → 4.4 retry scope excludes `values_update`;
M-C → moot for name lookup (the scope was withdrawn) but its duplicate-create
warning is now an accepted, documented consequence in sections 2 and 7, and
the index is authoritative again in 4.4 and 4.10; M-D → **confirmed
correct**, 4.2 rewritten and the decision superseded in section 2; M-E → 4.3
`anchor.history`, real intervals, constants re-derived; M-F → 4.9
placeholders withheld from the AI's option list; M-G → 4.6 multiset
reconciliation against a recorded baseline, per block; M-H → nine new cases
in section 5. Minors: n1 `run.sh` fact corrected below; n2 `seed_state.py`
runs in the new image (Phase 4 step 3); n3 `/months` lists 2026 months; n4
`DUMMY_CACHED` removal moved to the deletion commit; n5
`PERSONLIJKE_REKENING` spelling; n6 `/resume [upload_id]`; n7
`manually_switched` marked vestigial; n8 block-assignment rule stated in 4.5;
n9 placeholder script rollback line; n10 image tagged before rebuild; n11
reconciliation stated per block; n12 `AI_BUDGET_TRIP_ACTION` makes the dump a
choice; n13 `sheet_shape.py --summary`.

Round 4 (2026-09-21, same instance, revision 5): NEEDS REWORK, 1 critical, 5
major, 9 minor. No FIX-CHURN, but the reviewer noted that its blocking
findings sat predominantly in 4.6, 4.7, 4.3 and 4.4 — all rewritten after the
baseline — and that a round 5 concentrating blockers there again would trip
the breaker. It also raised a **valid LEDGER GAP**: revision 5's round-4
ledger omitted section 2, which had been rewritten (the superseded sheet-lookup
row and the new accepted-consequence row); the gap is corrected in the round-5
submission. The tunnel-vision check again endorsed the direction and named one
regression: M-K, the positional reconciliation baseline, is round 2's K1
defect inside the fix for M-G. C-C → 4.7 `rows` populated at `split`; M-I →
4.7 `appending` one-way door, "or write" dropped from per-period isolation;
M-J → 4.5/4.6/4.7 `first_write_row` replaces the last-used row; M-K → 4.6
row-count and prefix validation with a content-matching fallback, plus a
`/sort` guard in 4.8; M-L → 4.3 seeds `history` from row dates, with the
reason recorded in section 11; M-N → 4.4 adjacency guard,
`GSHEET_CREATE_NONADJACENT`, and the `L8` propagation added to the accepted
consequence in section 2. Minors: p1 strong key from the pre-normalisation
remittance; p2 `/cancel` needs `confirm: true`; p3 and p4 cache/index wording;
p5 Phase 1 runs the behavioural totals check; p6 constants derivation cites
boundary-to-boundary 27-32 days; p7 section 11's spans table repaired; p8
`test_add_income_placeholder.py`; p9 DoD grep aligned with Phase 3.

Round 5 (2026-09-21, same instance, revision 6): NEEDS REWORK, 0 critical, 4
major, 6 minor, and **FIX-CHURN tripped** on 4.5, 4.6, 4.7 and 4.1's
per-period line — blocking findings in post-baseline text for a second
consecutive round. No LEDGER GAP. The reviewer's ground for tripping was
specific and worth recording: the append/reconcile contract had been defective
in three consecutive revisions, each time in a different single detail
(revision 4 set-subtracted; revision 5 was off by one against a last-used-row
baseline; revision 6 compared a prefix against a baseline it never recorded),
which is the signature of an algorithm described in prose rather than
specified. It also noted that M-R sits in **baseline** text (4.4 step 7,
unchanged since revision 4) made dangerous by a post-baseline addition, so one
blocker was not churn at all.

Per the breaker protocol, 4.5 to 4.7 are rewritten holistically in revision 7
rather than patched, with the contract restated as a numbered procedure, and
the result goes to a **fresh scrutinizer instance for one cold read** before
the loop resumes. M-O → 4.1 and 4.6 record-then-commit-then-flip, idempotent
`record_written`, over-record-never-under-record invariant; M-P → 4.5
`BlockBaseline` records `first_write_row` **and** `prefix`, and 4.6's step 2
compares the prefix digest, the row-count check dropped as inert; M-Q → 4.3
`label_sort_key`, 4.4 `newest(index)` chronological; M-R → 4.4 `lookup` versus
`resolve`, step 7 uses `lookup`. Minors: p10 empty-`periods` run re-runs from
the start; p11 the content fallback's consequence stated and surfaced in the
summary; p12 constants comment; p13 `seed_state.py` row mentions `history`;
p14 writer test names both baseline fields; p15 nothing enters the index
before step 8 completes.

Cold read (2026-09-21, **fresh instance**, revision 7, per the breaker
protocol): NEEDS REWORK, 2 critical, 4 major, 9 minor. It endorsed the
direction independently and confirmed section 11's code claims by
spot-checking them against the repo. Its verdict on the rewrite: the ordering
questions were all genuinely fixed, but the recurrence had *moved* rather than
stopped — revision 7 specified the procedure over `RowTuple` and `read_block`,
neither of which it defined, which is the same species of defect one layer
down. It explicitly recommended **against** a third holistic pass in favour of
a bounded typed pass, so the churn counter resets and the normal loop resumes.
C1 → 4.5 `RowTuple`/`canonical()`/`UNFORMATTED_VALUE`, plus the Phase 1
real-API round-trip; C2 → 4.5/4.6 `first_write_row` is identity-only and
`commit_append` recomputes its append point; M1 → 4.5 `sort_by_date`
precondition, 4.1 closing sort, 4.7 write-failure behaviour; M2 → 4.6
`record_audit` split from `record_written`, `remove_rows` absent-tuple
behaviour and per-tuple cap, `--drop-created`; M3 → 4.4 step 7 requires
`written` or untouched; M4 → 4.5 positional `read_block`, `START` bound.
Minors 1-9: audit consumes `commit_append`'s return; empty-index adjacency;
the AI-budget-trip period always finishes under `write_flagged`;
`normalize_csv_data` writes a copy instead of rewriting in place; undo's
`--drop-created` and the softened 4.4 claim; anchor advance timing stated;
`/upload` guards on `appending`; `SUMMARY_FLAGGED_LINES` with a `.txt`
spillover; and three citation corrections.

**One correction to this plan's own evidence**, from minor 9. Revision 5
claimed `r"\bDUO\b"` fails against the description `"Duo uitkering"` because
the match is case-sensitive. That was wrong: `apply_categorization_rules` uses
`re.IGNORECASE` (`transaction_prompt.py:63`), under which it matches. The
conclusion — seed `history` from row dates — still holds, and more cleanly,
because `r"Anamata"` cannot match `"Salaris Ezra"` under any flag, so a
salary-opened boundary is invisible either way. Section 11 now states the
corrected argument.

Round 7 (2026-09-21, same instance, revision 8): NEEDS REWORK, 0 critical, 4
major, 6 minor. No FIX-CHURN (the counter reset after the cold read) and no
LEDGER GAP. It confirmed that the holistic rewrite dropped **no** fix from
rounds 1 to 5, tracing each one forward into revision 8, and answered the
`commit_append` race question in the negative by working the interleavings.
M-S → 4.6 binds `txs` alongside `intended` and both reconcile branches record
from `txs`; M-T → 4.6 reconciliation audits `found` on the positional path and
deliberately not on the fallback, with the asymmetry justified; M-U → 4.5 the
precondition moves to `compact_block` with an injected `is_appending`
predicate, and 4.7/4.8 sequence the remedies; M-V → 4.5 `canonical` is total.
Minors: q1 `record_audit` added to 4.1's flow; q2 `canonical` not applied to
`read_block`'s already-canonical output; q3 the injected predicate; q4 `prefix`
is always a digest; q5 pseudocode arity; q6 undo-coverage caveats on DoD 2 and
the section 7 risk row.

**M-V was load-bearing, not defensive**, and a measurement settled it before
the fix was written: `UNFORMATTED_VALUE` returns text for 70 date cells in
`02/2026` and serials everywhere else, and amounts come back `int` for whole
values (section 11). The reviewer flagged this as its own remaining
uncertainty and recommended checking it; the check changed the finding's
status rather than confirming it.

Round 8 (2026-09-21, same instance, revision 9): NEEDS REWORK, 0 critical, 2
major, 3 minor. The reviewer **emitted the FIX-CHURN line and recommended not
acting on it**, on the ground that the breaker exists to catch a section whose
*design* keeps failing under patching, and neither finding was that: M-W was a
fix that landed in five commentary sections and not in the normative one, and
M-X was one wrong operator in a branch added the round before. Since a
holistic pass had already run and the cold read had advised against a third,
the findings were fixed in place. No LEDGER GAP.

M-W → 4.5 now carries the per-slot `canonical` contract, and `read_block`'s
output is removed from the application list; M-X → 4.6's reconcile branches
partition indices of `txs` with the invariant
`len(found_idx) + len(remaining_idx) == len(intended)` asserted at runtime,
and `txs_of` is deleted. Minors: r1 the `compact_block` cross-reference
direction; r2 internal blanks described as possible rather than present, to
match the measurement; r3 the 70 text date cells measured as `DD-MM-YYYY` and
`seed_state.py` stated to canonicalise before comparing.

**M-W is worth recording as a process failure, not just a finding.** The
substance of the fix was right in revision 9 and its landing was incomplete,
which the reviewer noted was the fourth consecutive round with that shape. The
mechanical cause was a batched edit script that writes the file only at its
end, so an assertion failure late in the batch silently discarded earlier
successful replacements. Later edits verify every pattern before writing any
of them.

## 11. Facts verified in the repo and in Drive

**Summary formulas** (read with `valueRenderOption=FORMULA` on the template,
`04/2026` and `05/2026`; identical on all three). These settle round 3's C-B:

| Cell | Formula | Consequence |
|---|---|---|
| `E26` | `=sum(E27:E)` | **open-ended** — the expense placeholder at `B45`/`E45` is already counted, so `04/2026`'s three flagged rows are in its total today |
| `D26` | `=sum(D27:D)` | planned expenses, open-ended |
| `K26` | `=sum(K27:K44)` | bounded at 44, but the new income placeholder row is 35, so it is covered |
| `J26` | `=sum(J27:J44)` | planned income, same bound |
| `C22` / `I22` | `=E26` / `=K26` | totals feed the balance |
| `E17` | `=D17+(I22-C22)` | end balance; `D17 = if(isblank(L8);0;L8)` |
| `E45` | `=IF(ISBLANK($B45); ""; SUMIF(Transactions!$E:$E;$B45;Transactions!$C:$C))` | expense placeholder already wired |
| `K35`, `K36` | `=if(isblank($H35); ""; sumif(Transactions!$J:$J;$H35;Transactions!$H:$H))` | **already present and guarded by `isblank`** — writing the label into `H35` switches it on; no formula needs writing |

**Google OAuth scope classification** (verified 2026-09-21 against
`developers.google.com/drive/api/guides/api-specific-auth`): `drive.file`,
`drive.appdata` and `drive.install` are non-sensitive; `drive.apps.readonly`
is sensitive; **`drive`, `drive.readonly`, `drive.metadata`,
`drive.metadata.readonly`, `drive.activity(.readonly)`, `drive.meet.readonly`
and `drive.scripts` are restricted** and require a CASA security assessment —
a paid third-party audit revalidated every 12 months. `spreadsheets` is
sensitive: written justification at verification, no audit. This is why the
2026-09-21 name-lookup decision was withdrawn and the index is authoritative.

**Sheet ids, for seeding the index** (folder `Financiën`
`1QoYs19vu04_DFIszlfWOJP7BoQLEtfaG`; template
`1OSi4W3B3PrfCTQyxt3OreLmqSs4nXY82Wlg1_eohTs8`):

| Label | Spreadsheet id |
|---|---|
| 01/2026 | `1PE0gjLFBcO119H0p3EWD-InVzV2a8IA86utN8dF_UHw` |
| 02/2026 | `1-REOGzjHlOdXRQR1UOor-BA3KvPLesRqV-ks3P3zRG0` |
| 03/2026 | `1HXMu53v1T-gFsC8YREL9VScNsIs4h_CG-BSYw6EMwm4` |
| 04/2026 | `1hLCziEA-8MgupWHC5gLDLpmd3ZJlrWZcbMwnCfk6f4M` |
| 05/2026 | `1lOmS_Cd3vqoZyi-4SBrT3GTrRP9akqcO8l_0uWUlXM8` |
| 06/2026 | `14t0lxRlrCyXmpBk8heWBFOxzgVeG15YxdqjROp5t0Jw` |

The 2024 and 2025 months, `Spaarrekening *` and `Test Automation Sheet` are
out of scope (section 8) and are not seeded.

**Sheet structure** (structure only; no amounts, descriptions or names were
read). Every monthly sheet is a copy of the template with tabs `Summary` and
`Transactions`. `Transactions` has headers in rows 1-4 and data from row 5,
expenses in `B:E`, income in `G:J` (Date, Amount, Description, Category).
Amount cells carry the currency format `[$€]#,##0.00`; category cells carry
`ONE_OF_RANGE` validation, `=Summary!$B$27:$C` for expenses (open-ended) and
`=Summary!$H$27:$I$44` for income (bounded). `Summary` has 39 `SUMIF`
formulas over `Transactions!E`/`C` and `Transactions!J`/`H`, the starting
balance in `L8`, `D17 = if(isblank(L8);0;L8)` and the end balance
`E17 = D17+(I22-C22)`, with `C22 = E26` and `I22 = K26`. The expense category
table occupies `B28:B45`, ending with `! Nog in te delen !`; the income table
occupies `H28:H34` and has **no placeholder category**, with `H35:I44` free
inside the validation range. Spreadsheet properties: locale `nl_NL`, time
zone `Europe/Monaco`, `autoRecalc ON_CHANGE`, identical on the template and
on `04/2026`. The template has no month label cell. The template spells the
category `abonnementen`, `04/2026` spells it `Abonnementen`; Sheets `SUMIF`
is case-insensitive, so totals are unaffected.

**Drive layout** (2026-09-21, service account, folder-wide access). Folder
`Financiën` `1QoYs19vu04_DFIszlfWOJP7BoQLEtfaG` holds the 2026 months
directly, plus subfolders `2024` and `2025` (each with `Betaalrekening` and
`Spaarrekening` subfolders), the template
`1OSi4W3B3PrfCTQyxt3OreLmqSs4nXY82Wlg1_eohTs8`, `Spaarrekening Template` and
`Test Automation Sheet`. 31 spreadsheets are visible, all `canEdit`.
`Maandelijks Budget 12/2025` sits in the `2025` folder rather than a
`Betaalrekening` subfolder, so the folder layout is not perfectly regular —
one more reason the registry is an explicit index rather than a name or path
convention. Only the 2026 months are seeded; older ones are out of scope
(section 8).

**Real spans and volumes** (`scripts/sheet_shape.py`):

| Sheet | Expense span | Exp rows / last row | Income rows / last row |
|---|---|---|---|
| 01/2026 | 24-12-2025 → 22-01-2026 | 108 / 112 | 9 / 13 |
| 02/2026 | 23-01-2026 → 23-02-2026 (+1 row dated 23-03-2026) | 104 / 108 | 8 / 12 |
| 03/2026 | 24-02-2026 → 22-03-2026 | 87 / 91 | 7 / 11 |
| 04/2026 | 23-03-2026 → 23-04-2026 | 102 / 106 | 10 / 14 |
| 05/2026 | 24-04-2026 → 21-05-2026 | 99 / 103 | 7 / 11 |
| 06/2026 | empty | 0 | 0 |

**Boundary-to-boundary lengths**, which are the quantity 4.3's window guards:
24-12→23-01 is 30 days, 23-01→24-02 is 32, 24-02→23-03 is 27, 23-03→24-04 is
32 — so **27 to 32 days**. Measured *populated* spans are a different and
narrower quantity, 26 to 31 days, because a sheet's last row is not its
boundary. These are the numbers 4.3's constants derive from, and they are why
a fixed 30-day step and a 40-day forward window were both wrong.

Every sheet starts on the 23rd or 24th of the preceding month, which
independently validates the boundary rule and the day-15 label rule against
six months of history. The backlog is therefore the `05/2026` tail from
22-05-2026 plus `06/2026` through `09/2026`, roughly 450-500 rows at
about 100 expenses and 8 income per month. `! Nog in te delen !` appears in
one month only, 3 rows in `04/2026`, so the flagged volume after the change
should be small. `Transactions` row counts vary (179, 196, 230), so capacity
management matters. The Pi's `data/` holds no live cached, pending or failed
items.

**Cell types returned by `UNFORMATTED_VALUE`** (measured 2026-09-21 across
the five populated 2026 sheets; types only, no values read). This is what
makes `canonical`'s totality load-bearing rather than defensive:

| Sheet | date column | amount column |
|---|---|---|
| 01/2026 | serial (`int`) throughout | `int` 33 / `float` 75 |
| 02/2026 | **`str` on 69 of 104 expense cells and 1 of 8 income cells**; serial on the rest | `int` 32 / `float` 72 |
| 03/2026 | serial throughout | `int` 27 / `float` 60 |
| 04/2026 | serial throughout | mixed `int` / `float` |
| 05/2026 | serial throughout | mixed `int` / `float` |

So **70 date cells in `02/2026` are stored as text**, and amounts come back as
`int` whenever the value is whole. A `canonical` that assumed a serial date
and a float amount would raise on `plan_append` over `02/2026`'s prefix. No
block on any sheet contains an internal blank row today, so the positional
`read_block` is currently exercised only on contiguous blocks — the legacy
un-compacted sort is what could introduce one (section 4.5).

All 70 text-typed cells are in **`DD-MM-YYYY`** format (measured; no other
shape, no leading apostrophe, no stray whitespace), which is exactly the case
`canonical` converts explicitly rather than by its catch-all.

`02/2026` is also the sheet holding the stray 23-03-2026 row, so it was
evidently assembled differently from the others. It is not in the backlog
range, but `seed_state.py` reads every populated sheet, so **it canonicalises
each date before comparing** when taking a sheet's earliest row date — a
minimum taken across a mix of serials and unparsed strings is undefined. With
canonicalisation, `02/2026`'s boundary reads 23-01-2026, which is what
`anchor.history` needs and what rule 4 depends on.

**Code facts that change the work** (2026-09-21 inspection):

- `categorization_engine.py:123` imports `apply_categorization_rules` from
  `finance_core/ui/transaction_prompt.py:30-79`. The regex categoriser lives
  inside the UI module being deleted; it must move first (4.8).
- `google_sheets.py:198-260` (`write_transactions_to_sheet`) and its wrapper
  `export_to_google_sheets` are **dead code** — nothing calls them — and they
  are destructive: they `batch_clear("B2:E…", "G2:J…")` and write from row 2,
  which would wipe the header rows 2-4 of every real sheet. Deleted in
  Phase 1.
- `sort_transactions_by_date` writes the sorted rows back into
  `B{first}:E{last}` without compacting, so a blank row inside the block
  leaves a stale tail. It also caps at `B1:E500`. Replaced by
  `sheet_writer.sort_by_date` with `compact_block`.
- `csv_helper.normalize_csv_data` indexes `row[17]` with no length guard and
  rewrites the upload in place; `load_transactions_from_csv` does not carry
  column 15.
- `session_management.py:8` imports `GSHEET_EXPENSE_START_ROW` and
  `GSHEET_INCOME_START_ROW` at module scope, so those keys cannot be removed
  before the module is.
- `run.sh:51-55` exits 1 when `src/config/config_settings.py` is missing, but
  `run.sh:57-60` only **warns** about a missing
  `src/config/google_service_account.json` and continues. Revision 4 claimed
  it refuses; it does not.
- `run.sh:131` runs `docker system prune -f --volumes` on `--force-rebuild`,
  which can remove the previous image and with it the rollback.
- `transaction_prompt.py:14-19` reads both `DUMMY_CACHED` members inside a
  `try/except ImportError`, which would not catch the `AttributeError` raised
  if they were removed while the module still exists.
- `categorization_engine.py:164-167` and `:257-262` build the AI's category
  dictionaries excluding only `DUMMY_CACHED`, so `! Nog in te delen !` is
  already an answer the model can give confidently.
- **Boundary markers cannot be matched against a sheet's Description column.**
  Verified by running the real `CATEGORIZATION_RULES_INCOME` through
  `apply_categorization_rules`: counterparty `DUO Hoofdrekening` yields the
  description `"Duo uitkering"`, and `Anamata B.V.` with remittance
  `SALARISBETALING PERIODE 4` yields `"Salaris Ezra"`. Against those strings:
  `r"Anamata"` **cannot** match either, case-sensitively or not — the word is
  not in the output at all, so a salary-opened boundary is invisible. And
  `r"\bDUO\b"` matches `"Duo uitkering"` **only under `re.IGNORECASE`**,
  which `apply_categorization_rules` uses (`transaction_prompt.py:63`) but
  which 4.3 does not specify for the boundary matcher.

  So marker matching against a sheet is not uniformly impossible — it is
  *unreliable in a way that depends on an unstated flag and on which kind of
  row opened the month*, which is worse than either extreme for a seeding step
  the user is asked to confirm once. (An earlier revision of this plan claimed
  the DUO half fails outright; that claim was wrong under `IGNORECASE` and is
  corrected here.) Both markers match the raw CSV counterparty, so runtime
  detection is unaffected. Seeding `history` from row dates (4.3) avoids the
  question entirely and is exact by construction.
- Removal surface for the deleted modules: `bot.py:87-138`,
  `bot_commands.py:13, 264-276, 358`, `export.py:10, 84, 254, 283-306, 360,
  410`, `scripts/recategorize_pending.py:32-40, 67`,
  `scripts/retry_failed_transactions.py:18`.
- `create_categorization_engine` hardcodes the 0.75 threshold as a default
  argument; it becomes `AI_CONFIDENCE_THRESHOLD` (4.9).
- Existing tests: `tests/test_claude_provider_parse.py`,
  `tests/test_description_fallback.py`, 19 tests, green on 3.12.

**Privacy rule in force.** No real transaction data is read. Structure-only
inspection via `scripts/sheet_shape.py` and the two spike scripts (names,
counts, spans, category labels, formulas, API capabilities). The user runs
`scripts/make_fixture.py` on real exports; the fixture is reviewed by the
user before it is committed.
