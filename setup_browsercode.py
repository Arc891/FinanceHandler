#!/usr/bin/env python3
"""
One-time setup script for ASN Bank browsercode authentication.

This script must be run on the automation server where the scraper will run.
It opens a browser in visible mode to allow manual browsercode registration.

Usage:
    python setup_browsercode.py

What it does:
1. Launches browser in visible mode
2. Navigates to ASN Bank login page
3. Waits for you to manually complete browsercode setup
4. Saves session cookies to data/bank_session.json
5. Server becomes a "registered device" for future automation
"""

import asyncio
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def setup_browsercode():
    """Interactive browsercode setup on automation server."""

    try:
        # Import scraper
        sys.path.insert(0, str(Path(__file__).parent / "src"))
        from automation.bank_scraper import ASNBankScraper

        logger.info("=" * 60)
        logger.info("ASN Bank Browsercode Setup")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This script will:")
        logger.info("1. Open ASN Bank login page in a browser window")
        logger.info("2. Wait for you to complete browsercode registration")
        logger.info("3. Save session cookies for future automation")
        logger.info("")
        logger.info("Make sure you have:")
        logger.info("✓ Access to your phone for SMS/email verification codes")
        logger.info("✓ Chosen a 5-digit browsercode (write it down!)")
        logger.info("")

        input("Press ENTER to continue...")
        logger.info("")

        # Initialize scraper
        scraper = ASNBankScraper()

        # Launch browser in visible mode
        logger.info("🌐 Launching browser...")
        await scraper._init_browser(headless=False)

        # Create new context and page
        scraper.context = await scraper.browser.new_context()
        scraper.page = await scraper.context.new_page()

        # Navigate to login page
        logger.info(f"📄 Opening ASN Bank login page...")
        await scraper.page.goto(scraper.login_url, wait_until="networkidle")

        logger.info("")
        logger.info("=" * 60)
        logger.info("INSTRUCTIONS:")
        logger.info("=" * 60)
        logger.info("")
        logger.info("In the browser window that just opened:")
        logger.info("")
        logger.info("1. Click on the browsercode/device registration option")
        logger.info("   (Look for 'Browsercode' or 'Inloggen zonder app')")
        logger.info("")
        logger.info("2. Follow the steps to create your browsercode:")
        logger.info("   - Choose a 5-digit code (write it down!)")
        logger.info("   - Give your device a name (e.g., 'Automation Server')")
        logger.info("   - Complete verification (SMS/email codes)")
        logger.info("")
        logger.info("3. Login with your new browsercode to confirm it works")
        logger.info("")
        logger.info("4. Once logged in and you see the dashboard/overview page,")
        logger.info("   come back here and press ENTER")
        logger.info("")
        logger.info("=" * 60)
        logger.info("")

        # Wait for user to complete setup
        input("Press ENTER after you've successfully logged in with browsercode...")

        # Check if we're on the right page
        current_url = scraper.page.url
        logger.info(f"📍 Current URL: {current_url}")

        if "overzicht" in current_url.lower() or "dashboard" in current_url.lower():
            logger.info("✅ Detected successful login!")
        else:
            logger.warning("⚠️  Not on expected page, but continuing anyway...")
            confirm = input("Are you sure you're logged in? (y/N): ")
            if confirm.lower() != 'y':
                logger.info("❌ Setup cancelled")
                await scraper.cleanup()
                return False

        # Save session
        logger.info("💾 Saving session cookies...")
        await scraper._save_session()

        logger.info("")
        logger.info("=" * 60)
        logger.info("✅ BROWSERCODE SETUP COMPLETE!")
        logger.info("=" * 60)
        logger.info("")
        logger.info(f"Session saved to: {scraper.session_file}")
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Store your browsercode securely:")
        logger.info("   export ASN_BROWSERCODE='your-5-digit-code'")
        logger.info("")
        logger.info("2. Test the automation:")
        logger.info("   python -m automation.bank_scraper")
        logger.info("")
        logger.info("3. The scraper will now use your saved session + browsercode")
        logger.info("   for fully automated logins!")
        logger.info("")

        # Cleanup
        await scraper.cleanup()
        return True

    except KeyboardInterrupt:
        logger.info("\n❌ Setup interrupted by user")
        return False
    except Exception as e:
        logger.error(f"❌ Setup failed: {e}", exc_info=True)
        return False


def main():
    """Run the setup."""
    try:
        success = asyncio.run(setup_browsercode())
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
