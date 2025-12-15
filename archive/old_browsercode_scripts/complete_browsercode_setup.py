#!/usr/bin/env python3
"""
Complete browsercode setup with proper device registration.

This script guides you through:
1. Creating a browsercode (if you haven't already)
2. Logging in WITH that browsercode
3. Properly saving the device registration

Usage:
    export DISPLAY=:0
    python complete_browsercode_setup.py

You'll need your browsercode at hand!
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from automation.bank_scraper import ASNBankScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def complete_setup():
    """Complete browsercode setup with device registration."""

    print()
    print("=" * 70)
    print("  Complete Browsercode Setup & Device Registration")
    print("=" * 70)
    print()
    print("This will:")
    print("  1. Open ASN Bank login page")
    print("  2. Let you LOGIN with your browsercode")
    print("  3. Save the authenticated session")
    print("  4. Register this device properly")
    print()
    print("IMPORTANT: You should have already CREATED a browsercode.")
    print("           Now we need to LOGIN with it to register the device.")
    print()

    browsercode = input("Enter your 5-digit browsercode: ").strip()

    if len(browsercode) != 5 or not browsercode.isdigit():
        print("❌ Invalid browsercode! Must be 5 digits.")
        return False

    print()
    print(f"Browsercode: {browsercode}")
    print()
    print("Recommendation: Add this to your environment:")
    print(f"  export ASN_BROWSERCODE='{browsercode}'")
    print()

    input("Press Enter to continue...")
    print()

    scraper = ASNBankScraper()

    try:
        # Delete old session file if it exists (fresh start)
        if os.path.exists(scraper.session_file):
            logger.info(f"🗑️  Removing old session file...")
            os.remove(scraper.session_file)

        logger.info("🌐 Opening browser...")
        await scraper._init_browser(headless=False)

        # Create fresh context (no old cookies)
        scraper.context = await scraper.browser.new_context()
        scraper.page = await scraper.context.new_page()

        logger.info(f"📄 Navigating to login page...")
        await scraper.page.goto(scraper.login_url, wait_until="networkidle")

        await asyncio.sleep(2)

        print()
        print("=" * 70)
        print("BROWSER IS OPEN - PLEASE COMPLETE THESE STEPS:")
        print("=" * 70)
        print()
        print("In the browser window:")
        print()
        print("1. Look for 'Browsercode' or 'Inloggen met browsercode' option")
        print("   (NOT 'Create browsercode' - you already have one!)")
        print()
        print("2. Click on the browsercode login option")
        print()
        print(f"3. Enter your browsercode: {browsercode}")
        print()
        print("4. Complete the login")
        print()
        print("5. Wait until you see your dashboard/overzicht page")
        print()
        print("6. Come back here and press Enter")
        print()
        print("=" * 70)
        print()

        input("Press Enter AFTER you've successfully logged in...")

        # Check current URL
        current_url = scraper.page.url
        logger.info(f"📍 Current URL: {current_url}")

        if "inloggen" in current_url.lower() or "login" in current_url.lower():
            logger.warning("⚠️  Still on login page!")
            confirm = input("Are you sure you're logged in? (y/N): ")
            if confirm.lower() != 'y':
                logger.info("❌ Setup cancelled")
                await scraper.cleanup()
                return False

        # Navigate to verify we're really logged in
        logger.info("🔍 Verifying login by navigating to transactions page...")
        try:
            await scraper.page.goto(scraper.transactions_url, wait_until="networkidle", timeout=15000)
            final_url = scraper.page.url

            if "inloggen" in final_url.lower():
                logger.error("❌ Not logged in - redirected back to login page")
                await scraper.cleanup()
                return False

            logger.info(f"✅ Successfully navigated to: {final_url}")

        except Exception as e:
            logger.error(f"❌ Failed to verify login: {e}")
            await scraper.cleanup()
            return False

        # Save the session
        logger.info("💾 Saving authenticated session...")
        await scraper._save_session()

        # Set proper permissions
        os.chmod(scraper.session_file, 0o600)

        print()
        print("=" * 70)
        print("✅ SETUP COMPLETE!")
        print("=" * 70)
        print()
        print(f"Session saved to: {scraper.session_file}")
        print(f"Device is now registered!")
        print()
        print("Next steps:")
        print()
        print(f"1. Save your browsercode to environment:")
        print(f"   echo 'export ASN_BROWSERCODE=\"{browsercode}\"' >> ~/.bashrc")
        print(f"   source ~/.bashrc")
        print()
        print("2. Test the session:")
        print("   python test_browsercode_login.py")
        print()
        print("3. The automation should now work without manual intervention!")
        print()

        await scraper.cleanup()
        return True

    except KeyboardInterrupt:
        logger.info("\n❌ Interrupted by user")
        await scraper.cleanup()
        return False
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        await scraper.cleanup()
        return False


if __name__ == "__main__":
    success = asyncio.run(complete_setup())
    sys.exit(0 if success else 1)
