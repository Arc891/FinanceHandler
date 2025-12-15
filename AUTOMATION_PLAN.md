# ASN Bank Automation Plan

## Authentication Strategy: Browsercode

### Decision Summary

**Chosen Method:** Browsercode (5-digit PIN)
**Why:** Solves QR code refresh problem (4-5 sec), no second device needed, fully automatable

### Authentication Methods Compared

| Method | Automation | User Intervention | Decision |
|--------|-----------|-------------------|----------|
| **Browsercode** | ✅ High | One-time setup | **SELECTED** |
| QR Code | ❌ Not viable | Every 4-5 seconds | Rejected |
| Username/Password + SMS | ⚠️ Low | Every login | Rejected |
| PSD2 API | ✅ High | 180-day consent | Future option |

### Key Constraints Solved

1. **QR Code Refresh:** QR codes change every 4-5 seconds → impossible to scan/automate
2. **Device Paradox:** Can't scan QR from same device displaying it
3. **Manual Intervention:** Need fully automated solution after initial setup

## Implementation Plan

### Phase 1: Initial Setup (On Automation Server)

**One-time manual setup required:**

```bash
# Run on automation server
python setup_browsercode.py
```

**What happens:**
1. Browser opens in visible mode
2. Navigate to ASN Bank login
3. Manually create browsercode (5 digits)
4. Verify with SMS/email codes
5. Cookie saved to `data/bank_session.json`
6. Server becomes "registered device"

**Important:** Must be done on automation server, not dev machine

### Phase 2: Code Changes

#### 1. Update `src/automation/bank_scraper.py`

**Add browsercode login method:**
```python
async def login_with_browsercode(self, browsercode: str) -> bool:
    """Login using browsercode instead of QR."""
    await self.page.goto(self.login_url)

    # Click browsercode option
    await self.page.click("selector-for-browsercode-option")

    # Enter browsercode
    await self.page.fill("input[name='browsercode']", browsercode)
    await self.page.click("button[type='submit']")

    # Wait for login success
    await self.page.wait_for_url("**/overzicht**", timeout=30000)
    await self._save_session()
    return True
```

**Update selectors:** Inspect ASN Bank login page for actual element selectors

#### 2. Update `src/config_settings.example.py`

**Add browsercode config:**
```python
# ASN Bank Browsercode (5-digit code)
ASN_BROWSERCODE = os.environ.get('ASN_BROWSERCODE', '')
```

#### 3. Update `src/api/automation_endpoints.py`

**Modify login endpoint:**
```python
@app.post("/api/login")
async def login_to_bank(x_api_key: str = Header(...)):
    from automation.bank_scraper import ASNBankScraper
    from config_settings import ASN_BROWSERCODE

    scraper = ASNBankScraper()

    # Check existing session first
    if await scraper.is_session_valid():
        return {"success": True, "message": "Session already valid"}

    # Login with browsercode
    success = await scraper.login_with_browsercode(ASN_BROWSERCODE)
    await scraper.cleanup()

    return {"success": success}
```

### Phase 3: Security

**Browsercode storage:**
```bash
# Use environment variable (recommended)
export ASN_BROWSERCODE="12345"

# Or in .env file (not committed to git)
echo "ASN_BROWSERCODE=12345" >> .env
```

**Session file permissions:**
```bash
chmod 600 data/bank_session.json
```

## Technical Details

### Cookie-Based Device Recognition

```
Registration Flow:
1. Create browsercode → ASN Bank sets persistent cookie
2. Cookie = unique device identifier
3. Future logins:
   - Cookie present → Allow browsercode login
   - Cookie missing → Reject (unrecognized device)
```

### Session Persistence

- **Storage:** Playwright `storage_state` → `data/bank_session.json`
- **Duration:** Survives browser restarts (until cookie expires)
- **Invalidation:** 13 months inactivity, manual logout, cookie deletion
- **Device Limit:** Max 10 registered devices per account

### Device Portability

❌ **Don't copy cookies between machines** - triggers fraud detection
✅ **Do setup browsercode on each server individually**

## Implementation Checklist

### Setup
- [ ] Run `setup_browsercode.py` on automation server
- [ ] Store browsercode in environment variable
- [ ] Verify `data/bank_session.json` created

### Code Changes
- [ ] Add `login_with_browsercode()` to bank_scraper.py
- [ ] Update element selectors (inspect ASN login page)
- [ ] Add browsercode to config_settings.py
- [ ] Update API endpoints
- [ ] Remove/deprecate QR code methods

### Testing
- [ ] Test browsercode login flow
- [ ] Test session persistence after restart
- [ ] Test CSV download automation
- [ ] Test error handling (invalid code, expired session)

### Documentation
- [ ] Update CLAUDE.md with browsercode setup
- [ ] Update README.md installation steps
- [ ] Document environment variables

### Security
- [ ] Browsercode stored as env var (not hardcoded)
- [ ] Session file permissions set to 600
- [ ] No credentials in git history
- [ ] Logging doesn't expose browsercode

## Alternative: PSD2 API (Future)

If needed for commercial use:
- Register as TPP with ASN Bank
- Use official OAuth2 API
- 180-day consent duration
- No web scraping needed

**Current assessment:** Browsercode sufficient for personal use

## Success Criteria

✅ Fully automated downloads
✅ No manual intervention after setup
✅ Session persists across restarts
✅ Secure browsercode storage
✅ Works on automation server

## Rollback Plan

If browsercode fails:
- Keep both methods available
- Add config flag: `USE_BROWSERCODE = True/False`
- Switch between methods via config

## Estimated Effort

- Initial setup: 30 minutes
- Code changes: 2-3 hours
- Testing: 1 hour
- Total: ~4 hours
