#!/usr/bin/env python3
"""
Test that the persistent profile works and device stays registered.

This proves that the device registration persists across browser restarts.

Usage:
    export DISPLAY=:0
    python test_persistent_profile.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_persistent_profile():
    """Test reusing the persistent profile."""
    from playwright.async_api import async_playwright

    profile_dir = Path(__file__).parent / "data" / "browser_profile"

    if not profile_dir.exists():
        logger.error(f"❌ Profile directory not found: {profile_dir}")
        logger.error("   Please run setup_persistent_browsercode.py first!")
        return False

    print()
    print("=" * 70)
    print("  Testing Persistent Browser Profile")
    print("=" * 70)
    print()
    print(f"Profile: {profile_dir}")
    print()
    print("This will:")
    print("  1. Load the existing browser profile")
    print("  2. Navigate to ASN Bank")
    print("  3. Check if you're still logged in")
    print("  4. Verify device is still registered")
    print()
    print("=" * 70)
    print()

    input("Press Enter to test...")
    print()

    playwright = await async_playwright().start()

    try:
        logger.info("🔧 Loading persistent profile...")

        # Load the same profile - all cookies/tokens should be there!
        context = await playwright.firefox.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={'width': 1280, 'height': 720},
            locale='nl-NL',
            timezone_id='Europe/Amsterdam'
        )

        page = context.pages[0] if context.pages else await context.new_page()

        logger.info("✅ Profile loaded")

        # Navigate to protected page
        logger.info("🌐 Navigating to transactions page...")
        await page.goto("https://www.asnbank.nl/online/web/onlinebankieren/", wait_until="networkidle", timeout=15000)

        current_url = page.url
        logger.info(f"📍 Current URL: {current_url}")

        print()
        print("=" * 70)

        if "inloggen" in current_url.lower():
            print("❌ FAILED - Redirected to login page")
            print("=" * 70)
            print()
            print("Session expired or device not registered properly.")
            print()
            print("What you should see on the page:")
            print("  - If you see 'Login with browsercode': Device IS registered")
            print("  - If you see 'Create browsercode': Device NOT registered")
            print()
            result = False
        else:
            print("✅ SUCCESS - Still logged in!")
            print("=" * 70)
            print()
            print(f"You're on: {current_url}")
            print()
            print("The persistent profile works!")
            print("Device registration persisted across browser restarts!")
            print()
            result = True

        print()
        input("Press Enter to close...")

        await context.close()
        await playwright.stop()

        return result

    except KeyboardInterrupt:
        logger.info("\n❌ Interrupted")
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
    success = asyncio.run(test_persistent_profile())
    sys.exit(0 if success else 1)
