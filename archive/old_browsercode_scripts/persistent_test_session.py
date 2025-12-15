#!/usr/bin/env python3
"""
Persistent test session for ASN Bank scraper development.

Keeps a single browser session alive for testing without triggering rate limits.
Perfect for debugging selectors and testing download flows.

Usage:
    export DISPLAY=:0
    export ASN_BROWSERCODE="your-5-digit-code"
    python persistent_test_session.py

The browser will stay open and you can:
- See it in your screen share
- Use Playwright MCP to inspect elements
- Test different flows without re-logging in
- Keep session alive during development

Press Ctrl+C to cleanly close when done.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from automation.bank_scraper import ASNBankScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PersistentTestSession:
    """Manages a persistent browser session for testing."""

    def __init__(self):
        self.scraper = None
        self.running = False
        self.last_activity = None

    async def ensure_logged_in(self):
        """Ensure we're logged in (only happens once)."""
        browsercode = os.environ.get('ASN_BROWSERCODE', '')

        # Check if session is already valid
        if await self.scraper.is_session_valid():
            logger.info("✅ Existing session is valid!")
            return True

        # Need to login
        if not browsercode:
            logger.error("❌ ASN_BROWSERCODE not set and session expired")
            logger.error("   Please set: export ASN_BROWSERCODE='your-code'")
            return False

        logger.info("🔐 Logging in with browsercode...")
        success = await self.scraper.login_with_browsercode(browsercode, headless=False)

        if not success:
            logger.error("❌ Login failed")
            return False

        logger.info("✅ Login successful!")
        return True

    async def navigate_to_page(self, url: str):
        """Navigate to a specific page."""
        logger.info(f"🌐 Navigating to: {url}")
        await self.scraper.page.goto(url, wait_until="networkidle")
        self.last_activity = datetime.now()
        logger.info(f"📍 Current URL: {self.scraper.page.url}")

    async def keepalive(self):
        """Send periodic keepalive to prevent session timeout."""
        while self.running:
            # Wait 5 minutes between keepalives
            await asyncio.sleep(300)

            if not self.running:
                break

            try:
                # Gentle keepalive: just evaluate a simple JS expression
                # This tells the server we're still active without clicking anything
                await self.scraper.page.evaluate("() => document.title")
                logger.info("💓 Keepalive sent (session stays active)")
                self.last_activity = datetime.now()
            except Exception as e:
                logger.warning(f"⚠️  Keepalive failed: {e}")

    async def run(self):
        """Main session loop."""
        print()
        print("=" * 70)
        print("  Persistent Test Session")
        print("=" * 70)
        print()
        print("This script will:")
        print("  1. Login once (using existing session or browsercode)")
        print("  2. Navigate to the transactions/download page")
        print("  3. Keep the browser open for testing")
        print("  4. Send periodic keepalives to prevent timeout")
        print()
        print("The browser will appear in your screen share.")
        print("You can inspect elements, test clicks, etc.")
        print()
        print("Press Ctrl+C when you're done testing.")
        print()
        print("=" * 70)
        print()

        try:
            # Initialize scraper
            self.scraper = ASNBankScraper()
            self.running = True

            # Initialize browser (not headless)
            await self.scraper._init_browser(headless=False)

            # Load session or create new context
            if os.path.exists(self.scraper.session_file):
                logger.info("📂 Loading existing session...")
                self.scraper.context = await self.scraper.browser.new_context(
                    storage_state=self.scraper.session_file
                )
            else:
                logger.info("🆕 Creating new browser context...")
                self.scraper.context = await self.scraper.browser.new_context()

            self.scraper.page = await self.scraper.context.new_page()

            # Ensure we're logged in
            if not await self.ensure_logged_in():
                logger.error("❌ Could not establish session")
                return False

            # Navigate to transactions page
            await self.navigate_to_page("https://www.asnbank.nl/online/web/onlinebankieren/")

            print()
            print("=" * 70)
            print("✅ SESSION READY")
            print("=" * 70)
            print()
            print(f"Browser is open at: {self.scraper.page.url}")
            print()
            print("You can now:")
            print("  • See the browser in your screen share")
            print("  • Use Playwright MCP tools to inspect elements")
            print("  • Navigate around manually in the browser")
            print("  • Test different flows")
            print()
            print("Session will stay alive with automatic keepalives.")
            print()
            print("Press Ctrl+C to close when done.")
            print()
            print("=" * 70)
            print()

            # Start keepalive task
            keepalive_task = asyncio.create_task(self.keepalive())

            # Wait indefinitely (until Ctrl+C)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass

            # Cancel keepalive
            self.running = False
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass

            return True

        except KeyboardInterrupt:
            logger.info("\n⚠️  Interrupted by user")
            return True
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            return False
        finally:
            self.running = False
            if self.scraper:
                logger.info("🧹 Cleaning up...")
                await self.scraper.cleanup()
                logger.info("✅ Browser closed")


async def main():
    """Entry point."""
    session = PersistentTestSession()
    success = await session.run()
    return 0 if success else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
        sys.exit(0)
