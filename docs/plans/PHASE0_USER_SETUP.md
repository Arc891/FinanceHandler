# Phase 0: setup steps on the user's side

Companion to `MULTI_MONTH_UPLOAD_PLAN.md` section 6. These are the steps only
the user can do: they need the user's Google account, bank login or real
transaction data. Written 2026-09-24; the Google console labels were checked
against Google's documentation on that date.

Status: tick each box as it is done.

- [ ] 1. Income placeholder applied to the sheets (dry run checked 2026-09-25: all seven `would-write`)
- [ ] 2. OAuth client created and saved to `data/google/oauth_client.json`
- [ ] 3. Consent screen tested: "unverified" warning, not "access blocked" (**gates Phase 1**)
- [ ] 4. Bank sequence number compared across two exports: same / different
- [ ] 5. Fixture `tests/fixtures/multi_month.csv` made, reviewed and committed (**gates Phase 2**)

All commands run from the project root: `cd ~/Coding/FinanceAutomation`.

---

## 1. Add the income placeholder to the sheets (2 minutes)

```
venv/bin/python scripts/add_income_placeholder.py            # dry run, reads only
venv/bin/python scripts/add_income_placeholder.py --apply
```

- The dry run must show `would-write` on all seven lines (template,
  01/2026 to 06/2026). After `--apply` every line must say `written`.
- It writes one cell per sheet, `Summary!H35`, and nothing else.
- Undo: clear `Summary!H35` on that sheet, or use File > Version history.
- Running it again is safe: already-patched sheets show `already-done`.

## 2. Create the OAuth client in Google Cloud (10 minutes)

Sign in to <https://console.cloud.google.com> with the Google account that
**owns the `Financiën` folder**, and select the project `asnexport`.

1. **APIs**: ☰ > APIs & Services > Library. Check that **Google Sheets API**
   and **Google Drive API** both say "Enabled". If one does not, open it and
   click **Enable**.
2. **Branding**: ☰ > **Google Auth Platform** > **Branding**. If you see
   **Get Started**, click it:
   - App name: `Finance Bot`
   - User support email: your address
   - Audience: **External**
   - Contact email: your address
   - Tick the policy agreement, then **Continue** > **Create**
3. **Data Access** > **Add or Remove Scopes**. Tick exactly these two:
   - `https://www.googleapis.com/auth/spreadsheets`
   - `https://www.googleapis.com/auth/drive.file`

   Then **Update** > **Save**. Do **not** add any other `drive` scope, even if
   the console suggests one. They are "restricted", and Google then requires a
   paid security audit every year.
4. **Audience** > **Publish app** > confirm. The status must read
   **In production**. In "Testing" Google expires the login after 7 days. You
   do not need to submit for verification.
5. **Clients** > **Create Client**:
   - Application type: **Desktop app**
   - Name: `finance-bot-desktop`
   - **Create**, then **download the JSON right away**. Google only shows the
     client secret once, at creation. If you miss it, delete the client and
     create a new one.
6. Put the file in place (Windows downloads are at
   `/mnt/c/Users/Ezra/Downloads/`):

   ```
   mkdir -p data/google
   mv /mnt/c/Users/Ezra/Downloads/client_secret_*.json data/google/oauth_client.json
   chmod 600 data/google/oauth_client.json
   ```

   `data/google/` is gitignored.

## 3. Test the consent screen (3 minutes, gates Phase 1)

Run this in **your own terminal, not through `!` in a Claude session**, so
the saved token never lands in a conversation:

```
venv/bin/google-oauthlib-tool --client-secrets data/google/oauth_client.json \
  --scope https://www.googleapis.com/auth/spreadsheets \
  --scope https://www.googleapis.com/auth/drive.file \
  --save --credentials data/google/consent_test.json
```

1. If no browser opens, copy the printed URL into your Windows browser. Pick
   the account that owns `Financiën`.
2. **Expected**: "Google hasn't verified this app". Click **Advanced** >
   **Go to Finance Bot (unsafe)** > **Continue**. The terminal prints
   `credentials saved`. Then remove the test token:
   `rm data/google/consent_test.json`
3. **If you get "Access blocked" instead**: stop and report it. That is the
   plan's fallback case (plan 4.2, plan B), decided together before Phase 1.

## 4. Check the bank sequence number (5 minutes)

1. In ASN, download two exports whose date ranges share at least one day
   (for example the 1st to the 10th, and the 10th to the 20th).
2. Open both and find the same transactions on the shared day.
3. Compare column 15: the 16th column, the number just after the
   transaction codes.
4. Report only "same" or "different". Do not paste the rows.

If they are the same, the number can join the duplicate-detection key (plan 4.6).

## 5. Make the test fixture (10 minutes, gates Phase 2)

1. Download one ASN export that covers **at least three DUO or salary
   payments**, for example 01-06-2026 to today.
2. Anonymise it and check its shape:

   ```
   venv/bin/python scripts/make_fixture.py /mnt/c/Users/Ezra/Downloads/<export>.csv tests/fixtures/multi_month.csv
   venv/bin/python scripts/sheet_shape.py csv tests/fixtures/multi_month.csv
   ```

   The second command must show a DUO or SALARIS **income** marker on three
   or more dates.
3. Open `tests/fixtures/multi_month.csv` and check that no real names, IBANs
   or reference numbers are left.
4. If it is clean, commit it. If something slipped through, report which
   kind of field it was, not the value.
5. Delete the real export.

---

## After these steps

- Step 3 done → Phase 1 (Google layer) can start.
- Step 5 done → Phase 2 (month splitting) can start. It does not need the
  OAuth client, so Phase 1 and Phase 2 can run in either order.

Sources checked 2026-09-24:
[configure OAuth consent](https://developers.google.com/workspace/guides/configure-oauth-consent),
[create credentials](https://developers.google.com/workspace/guides/create-credentials),
[manage OAuth clients](https://support.google.com/cloud/answer/15549257),
[publishing status](https://support.google.com/cloud/answer/15549945).
