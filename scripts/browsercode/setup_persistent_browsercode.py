#!/usr/bin/env python3
"""
FOOLPROOF Browsercode Setup with Persistent Browser Profile.

This uses Playwright's persistent context which creates a REAL browser profile
directory (like using regular Firefox). Everything persists automatically:
- Cookies
- IndexedDB
- localStorage
- Device fingerprints
- ALL security tokens

The device registration will stick permanently because it's a real browser profile.

Usage:
    export DISPLAY=:0
    python setup_persistent_browsercode.py
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def setup_with_persistent_profile():
    """
    Setup browsercode using a persistent browser profile.

    This is 100% foolproof because it creates a real browser profile
    directory that persists everything automatically.
    """
    from playwright.async_api import async_playwright

    # Profile directory - this is where EVERYTHING will be stored
    profile_dir = Path(__file__).parent / "data" / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 70)
    print("  FOOLPROOF Browsercode Setup")
    print("=" * 70)
    print()
    print("This creates a REAL browser profile (like your regular Firefox).")
    print("Everything persists automatically - no manual cookie export!")
    print()
    print(f"Profile location: {profile_dir}")
    print()
    print("Steps:")
    print("  1. Browser will open with persistent profile")
    print("  2. Navigate to ASN Bank login")
    print("  3. CREATE a new browsercode (write it down!)")
    print("  4. LOGIN with that browsercode immediately")
    print("  5. Device is registered permanently")
    print()
    print("=" * 70)
    print()

    input("Press Enter to start...")
    print()

    playwright = await async_playwright().start()

    # Use persistent context - this is the KEY to making it work!
    logger.info(f"🔧 Creating persistent browser profile at: {profile_dir}")

    try:
        # This creates a REAL browser with a REAL profile directory
        # Everything persists automatically, just like using regular Firefox
        context = await playwright.firefox.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={'width': 1280, 'height': 720},
            locale='nl-NL',
            timezone_id='Europe/Amsterdam'
        )

        page = context.pages[0] if context.pages else await context.new_page()

        logger.info("✅ Browser opened with persistent profile")
        logger.info("   This profile will remember EVERYTHING")

        # Navigate to ASN Bank login
        logger.info("🌐 Navigating to ASN Bank...")
        await page.goto("https://www.asnbank.nl/inloggen", wait_until="networkidle")

        await asyncio.sleep(2)

        print()
        print("=" * 70)
        print("BROWSER IS OPEN - COMPLETE BROWSERCODE SETUP")
        print("=" * 70)
        print()
        print("In the browser window, do the following:")
        print()
        print("STEP 1: Create Browsercode")
        print("  - Click 'Maak een browsercode' or similar")
        print("  - Choose a 5-digit code (WRITE IT DOWN!)")
        print("  - Give device a name (e.g., 'Automation Pi')")
        print("  - Complete SMS/email verification")
        print()
        print("STEP 2: Login with Browsercode (IMPORTANT!)")
        print("  - After creating it, LOGIN with your new code")
        print("  - This registers the device properly")
        print()
        print("STEP 3: Verify")
        print("  - Wait until you see dashboard/overzicht")
        print("  - Come back here and press Enter")
        print()
        print("=" * 70)
        print()

        # Get browsercode from user
        browsercode = input("Enter the browsercode you just created (5 digits): ").strip()

        while len(browsercode) != 5 or not browsercode.isdigit():
            print("❌ Must be exactly 5 digits!")
            browsercode = input("Enter the browsercode: ").strip()

        print()
        print(f"✅ Browsercode: {browsercode}")
        print()

        input("Press Enter AFTER you've logged in with the browsercode...")

        # Check URL
        current_url = page.url
        logger.info(f"📍 Current URL: {current_url}")

        # Try navigating to transactions to verify login
        logger.info("🔍 Verifying login...")
        try:
            await page.goto("https://www.asnbank.nl/online/web/onlinebankieren/", wait_until="networkidle", timeout=15000)
            final_url = page.url

            if "inloggen" in final_url.lower():
                logger.error("❌ Not logged in - still on login page")
                logger.error("   Please complete the login and try again")
                await context.close()
                await playwright.stop()
                return False

            logger.info(f"✅ Verified - on page: {final_url}")

        except Exception as e:
            logger.warning(f"⚠️  Verification failed: {e}")
            confirm = input("Are you sure you're logged in? (y/N): ")
            if confirm.lower() != 'y':
                await context.close()
                await playwright.stop()
                return False

        print()
        print("=" * 70)
        print("✅ SETUP COMPLETE!")
        print("=" * 70)
        print()
        print(f"Browser profile saved to: {profile_dir}")
        print()
        print("This profile contains:")
        print("  ✅ Device registration")
        print("  ✅ All cookies")
        print("  ✅ All security tokens")
        print("  ✅ Browser fingerprint")
        print()
        print("The device is now PERMANENTLY registered!")
        print()
        print("Next steps:")
        print()
        print(f"1. Save your browsercode:")
        print(f"   echo 'export ASN_BROWSERCODE=\"{browsercode}\"' >> ~/.bashrc")
        print(f"   source ~/.bashrc")
        print()
        print("2. Update bank_scraper.py to use persistent context")
        print()
        print("3. Test reusing the profile (close browser and run again)")
        print()
        print("=" * 70)
        print()

        input("Press Enter to close browser...")

        # Close gracefully
        await context.close()
        await playwright.stop()

        logger.info("✅ Browser closed, profile saved")

        return True

    except KeyboardInterrupt:
        logger.info("\n❌ Interrupted by user")
        try:
            await context.close()
            await playwright.stop()
        except:
            pass
        return False
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        try:
            await context.close()
            await playwright.stop()
        except:
            pass
        return False


if __name__ == "__main__":
    success = asyncio.run(setup_with_persistent_profile())
    sys.exit(0 if success else 1)
