# Browsercode Automation - Status & Next Steps

**Status**: ⏸️ **PAUSED - Awaiting ASN Bank Legal Clarification**

**Date**: 2025-12-15

---

## What Was Completed

### 1. Configuration (src/config_settings.py:67-87)
- ✅ Added `ASN_BROWSERCODE` environment variable support
- ✅ Added `API_SECRET_KEY` for API authentication
- ✅ Added `BANK_SESSION_FILE` and `BANK_DOWNLOAD_DIR` paths
- ✅ All configs read from environment variables (secure)

### 2. API Endpoints (src/api/automation_endpoints.py)
- ✅ Created `/api/login` endpoint for browsercode authentication
- ✅ Deprecated `/api/qr-login` (QR codes refresh too fast)
- ✅ Added proper authentication with API key headers
- ✅ Session validation before attempting login

### 3. Bank Scraper - Browsercode Login (src/automation/bank_scraper.py:162-318)
- ✅ Implemented `login_with_browsercode()` method
- ✅ Multiple selector fallbacks for finding elements
- ✅ Debug screenshots on errors
- ✅ Session saving after successful login

### 4. Setup Scripts
**Keep these files:**
- ✅ `setup_persistent_browsercode.py` - **RECOMMENDED APPROACH**
  - Uses Playwright persistent context (real browser profile)
  - Device registration persists permanently
  - No manual cookie export needed

- ✅ `test_persistent_profile.py` - **TESTING TOOL**
  - Verifies persistent profile works
  - Tests device registration persistence

**Can remove (old approaches):**
- ❌ `setup_browsercode.py` - Old storage_state approach
- ❌ `test_browsercode_login.py` - Old testing script
- ❌ `complete_browsercode_setup.py` - Old manual setup
- ❌ `persistent_test_session.py` - Development testing only

---

## Critical Discovery: Device Registration

### Problem Encountered
- **storage_state (cookies only)** is NOT sufficient for device registration
- ASN Bank uses more than cookies to recognize devices:
  - IndexedDB
  - Service Workers
  - Browser fingerprinting
  - Additional security tokens

### Solution Found
**Playwright Persistent Context** = Real browser profile directory
```python
# OLD (incomplete):
context = await browser.new_context(storage_state="session.json")

# NEW (foolproof):
context = await playwright.firefox.launch_persistent_context(
    user_data_dir="./data/browser_profile"
)
```

**Why it works:**
- Creates actual browser profile directory (like regular Firefox)
- Stores IndexedDB, Service Workers, all tokens automatically
- Browser fingerprint stays consistent
- Device registration persists across restarts

---

## What Still Needs to Be Done

### If ASN Bank Approves Automation:

#### 1. Update bank_scraper.py to Use Persistent Context
Current implementation uses `storage_state`. Needs refactor to:
```python
async def _init_browser_persistent(self, profile_dir: str):
    """Initialize with persistent context for device registration."""
    playwright = await async_playwright().start()
    self.context = await playwright.firefox.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=True  # Can be headless after initial setup
    )
    self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
```

#### 2. One-Time Setup Process
1. Run `setup_persistent_browsercode.py` on the automation server
2. Manually create browsercode and login in visible browser
3. Profile saved to `data/browser_profile/`
4. Device permanently registered

#### 3. Automated Operation
After setup:
- Load persistent context automatically
- Session persists (no re-login unless expired)
- If session expires: use browsercode for re-auth
- Download transactions via identified selectors

#### 4. Transaction Download Flow
**Still needs implementation:**
- Navigate to transaction export page
- Identify "Vanaf laatste download" button (see user's download link)
- Click download/export button
- Save CSV to `data/bank_downloads/`
- Parse and process transactions

---

## Legal/Compliance Considerations

### ASN Bank has Official PSD2 APIs
- [API Documentation](https://openbanking.asnbank.nl/documentation.html)
- Supports Account Information Services (AIS)
- Requires TPP registration with De Nederlandsche Bank

### Options:
1. **Official API** (if available for personal use)
   - Fully legal and supported
   - 180-day consent duration
   - OAuth2 authentication

2. **Personal Automation** (if ASN approves)
   - For own account only
   - Using official login methods (browsercode)
   - Once per day frequency (safe)

3. **Manual Process** (fallback)
   - Keep Discord bot for categorization
   - Manual CSV upload from ASN Bank

---

## Security Notes

### Safe Practices Implemented:
- ✅ Browsercode stored in environment variable (not hardcoded)
- ✅ Persistent sessions (minimal login frequency)
- ✅ Single trusted device (Raspberry Pi)
- ✅ API authentication with secret keys
- ✅ Session files have 600 permissions

### Rate Limiting Research:
- Dutch banks use velocity rules (rapid repeated actions)
- Typical failed login threshold: ~5 attempts
- Our approach: Once daily, successful logins only ✅

---

## Files Overview

### Keep (Core Implementation):
```
src/
├── automation/
│   └── bank_scraper.py          # Core scraper (needs persistent context update)
├── api/
│   └── automation_endpoints.py  # FastAPI endpoints
└── config_settings.py           # Configuration

Root directory:
├── setup_persistent_browsercode.py  # ⭐ ONE-TIME SETUP (recommended)
├── test_persistent_profile.py       # ⭐ TESTING TOOL
└── BROWSERCODE_STATUS.md           # This file
```

### Remove (Development/Testing):
```
├── setup_browsercode.py            # Old approach
├── test_browsercode_login.py       # Old testing
├── complete_browsercode_setup.py   # Old manual setup
└── persistent_test_session.py      # Dev testing only
```

### Data Directories:
```
data/
├── browser_profile/          # ⭐ PERSISTENT PROFILE (if created)
├── bank_session.json         # Old storage_state (can remove)
├── bank_downloads/           # CSV downloads location
├── sessions/                 # Discord bot sessions
└── uploads/                  # Discord bot uploads
```

---

## Next Steps

### Immediate:
- ⏸️ **WAIT for ASN Bank response on legality**

### If Approved:
1. Refactor `bank_scraper.py` to use persistent context
2. Run one-time setup with `setup_persistent_browsercode.py`
3. Implement transaction download selectors
4. Test end-to-end download flow
5. Integrate with categorization workflow

### If Not Approved:
1. Remove automation code
2. Keep manual CSV upload via Discord
3. Consider official PSD2 API if available for personal use
4. Fall back to pure manual process

---

## Lessons Learned

1. **Device registration ≠ Just cookies**
   - Need full browser profile for persistence

2. **Playwright persistent context is key**
   - Real browser profile = permanent device identity

3. **One-time visible setup, then headless**
   - Initial browsercode creation needs GUI
   - After setup, can run headless

4. **Legal clarity first**
   - Always check ToS and get explicit approval
   - Personal use ≠ automatically allowed

---

## Questions for ASN Bank

When contacting ASN, ask:
1. Is automated access for personal account allowed?
2. Are there official APIs for personal use?
3. What is the policy on web scraping/automation?
4. Is there a TPP registration process for individuals?
5. Are there rate limits or restrictions to be aware of?

---

**Last Updated**: 2025-12-15 by Claude Code
**Status**: Awaiting legal clarification before proceeding
