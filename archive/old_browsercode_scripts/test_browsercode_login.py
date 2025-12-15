#!/usr/bin/env python3
"""
Test browsercode login with your saved code.

Usage:
    export DISPLAY=:0
    export ASN_BROWSERCODE="your-5-digit-code"
    python test_browsercode_login.py
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


async def test_browsercode():
    """Test browsercode login."""

    # Get browsercode from environment
    browsercode = os.environ.get('ASN_BROWSERCODE', '')

    if not browsercode:
        print("❌ Please set ASN_BROWSERCODE environment variable:")
        print("   export ASN_BROWSERCODE='your-5-digit-code'")
        return False

    print("=" * 70)
    print("Testing Browsercode Login")
    print("=" * 70)
    print(f"Browsercode: {browsercode}")
    print()

    scraper = ASNBankScraper()

    try:
        # First, check if session is already valid
        logger.info("🔍 Checking existing session...")
        if await scraper.is_session_valid():
            print()
            print("✅ Session is already valid!")
            print("   No need to login again.")
            print()
            print(f"Session file: {scraper.session_file}")
            print()
            print("You can now use the automation without any manual steps.")
            await scraper.cleanup()
            return True

        print()
        logger.info("⚠️  Session expired or invalid, attempting browsercode login...")
        print()
        print("🌐 Opening browser (it will appear in your screen share)...")
        print("   Watch for the login process...")
        print()

        # Attempt browsercode login (not headless so you can see what happens)
        success = await scraper.login_with_browsercode(browsercode, headless=False)

        if success:
            print()
            print("=" * 70)
            print("✅ SUCCESS! Browsercode login worked!")
            print("=" * 70)
            print()
            print(f"Session saved to: {scraper.session_file}")
            print()
            print("Next steps:")
            print("  1. Session will persist across restarts")
            print("  2. Test the scraper:")
            print("     cd src && python -m automation.bank_scraper")
            print()
            print("  3. Or start the API:")
            print("     cd src && python -m api.automation_endpoints")
            print()
            return True
        else:
            print()
            print("=" * 70)
            print("❌ Browsercode login failed")
            print("=" * 70)
            print()
            print("Check the error messages above or screenshots in /tmp/")
            print()
            print("Possible issues:")
            print("  • Incorrect browsercode")
            print("  • Browser couldn't find login elements (need to update selectors)")
            print("  • Session cookies not loaded properly")
            print()
            return False

    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return False
    finally:
        await scraper.cleanup()


if __name__ == "__main__":
    success = asyncio.run(test_browsercode())
    sys.exit(0 if success else 1)
