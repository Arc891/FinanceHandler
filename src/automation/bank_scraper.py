"""
ASN Bank scraper using Playwright for automated transaction downloads.

Handles:
- QR code login flow
- Session/cookie management
- CSV download with date filtering
- Error recovery and retry logic
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


class ASNBankScraper:
    """Scraper for ASN Bank with QR login and session management."""

    def __init__(self, session_file: str = "data/bank_session.json",
                 download_dir: str = "data/bank_downloads"):
        """
        Initialize the ASN Bank scraper.

        Args:
            session_file: Path to store session cookies
            download_dir: Directory to save downloaded CSV files
        """
        self.session_file = session_file
        self.download_dir = download_dir
        self.login_url = "https://www.asnbank.nl/inloggen"
        self.transactions_url = "https://www.asnbank.nl/online/web/onlinebankieren/"
        self.qr_timeout = 300  # 5 minutes for QR scan

        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # Ensure directories exist
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        os.makedirs(download_dir, exist_ok=True)

    async def _init_browser(self, headless: bool = True) -> None:
        """Initialize Playwright browser."""
        if self.browser is None:
            playwright = await async_playwright().start()
            self.browser = await playwright.firefox.launch(headless=headless)
            logger.info("✅ Browser launched")

    async def _load_session(self) -> bool:
        """Load session from saved cookies if available."""
        if not os.path.exists(self.session_file):
            logger.info("No saved session found")
            return False

        try:
            await self._init_browser()
            if self.browser is None:
                logger.error("❌ Browser initialization failed")
                return False

            self.context = await self.browser.new_context(storage_state=self.session_file)
            self.page = await self.context.new_page()
            assert self.page is not None, "Page initialization failed"
            logger.info("✅ Loaded session from cookies")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to load session: {e}")
            return False

    async def _save_session(self) -> None:
        """Save current session cookies to file."""
        if self.context:
            try:
                await self.context.storage_state(path=self.session_file)
                logger.info(f"✅ Session saved to {self.session_file}")
            except Exception as e:
                logger.error(f"❌ Failed to save session: {e}")

    async def login_with_qr(
            self, qr_save_path: str = "/tmp/asn_qr_login.png") -> Tuple[bool, str]:
        """
        Initiate QR login and save QR code for user to scan.

        Args:
            qr_save_path: Path to save QR code image

        Returns:
            Tuple of (success, qr_image_path or error_message)
        """
        try:
            # Show browser for QR scan
            await self._init_browser(headless=False)
            if self.browser is None:
                return False, "Browser initialization failed"

            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()

            logger.info(f"🌐 Navigating to {self.login_url}")
            assert self.page is not None, "Page initialization failed"
            await self.page.goto(self.login_url, wait_until="networkidle")

            # Wait for QR code to appear
            # Note: Actual selectors will need to be updated based on ASN
            # Bank's HTML structure
            logger.info("⏳ Waiting for QR code element...")

            try:
                # Try multiple possible QR code selectors
                qr_selectors = [
                    "img[alt*='QR']",
                    "img[alt*='qr']",
                    "canvas.qr",
                    ".qr-code img",
                    "[class*='qr'] img",
                    "img[src*='qr']"
                ]

                qr_element = None
                for selector in qr_selectors:
                    try:
                        qr_element = await self.page.wait_for_selector(selector, timeout=10000)
                        if qr_element:
                            logger.info(
                                f"✅ Found QR code with selector: {selector}")
                            break
                    except Exception:
                        continue

                if not qr_element:
                    # Fallback: screenshot the entire page
                    logger.warning(
                        "⚠️ Could not find QR code element, taking full page screenshot")
                    await self.page.screenshot(path=qr_save_path, full_page=True)
                else:
                    # Screenshot just the QR code
                    await qr_element.screenshot(path=qr_save_path)

                logger.info(f"📸 QR code saved to {qr_save_path}")

            except Exception as e:
                logger.error(f"❌ Failed to capture QR code: {e}")
                # Save debug screenshot
                debug_path = "/tmp/asn_login_debug.png"
                await self.page.screenshot(path=debug_path, full_page=True)
                return False, f"QR code not found. Debug screenshot: {debug_path}"

            # Poll for login success
            logger.info(f"⏳ Waiting up to {self.qr_timeout}s for QR scan...")

            try:
                # Wait for redirect to dashboard/transactions page after login
                # Adjust this URL based on actual ASN Bank post-login redirect
                await self.page.wait_for_url("**/overzicht**", timeout=self.qr_timeout * 1000)
                logger.info("✅ Login successful!")

                # Save session
                await self._save_session()

                return True, qr_save_path

            except Exception as e:
                logger.error(f"❌ Login timeout or failed: {e}")
                return False, f"Login timeout after {self.qr_timeout}s. Please scan QR code with ASN app."

        except Exception as e:
            logger.error(f"❌ QR login error: {e}")
            return False, str(e)

    async def login_with_browsercode(
            self, browsercode: str, headless: bool = False) -> bool:
        """
        Login using browsercode (5-digit PIN) instead of QR code.

        This method requires one-time setup on the automation server to register
        the device. Once registered, the session persists via cookies.

        Args:
            browsercode: 5-digit browsercode PIN
            headless: Whether to run browser in headless mode

        Returns:
            True if login successful, False otherwise
        """
        if not browsercode or len(
                browsercode) != 5 or not browsercode.isdigit():
            logger.error("❌ Invalid browsercode: must be 5 digits")
            return False

        try:
            await self._init_browser(headless=headless)
            if self.browser is None:
                logger.error("❌ Browser initialization failed")
                return False

            # Load existing session if available to preserve device
            # registration
            if os.path.exists(self.session_file):
                logger.info(
                    "📂 Loading existing session for device registration")
                self.context = await self.browser.new_context(storage_state=self.session_file)
            else:
                logger.info("🆕 Creating new browser context")
                self.context = await self.browser.new_context()

            self.page = await self.context.new_page()

            logger.info(f"🌐 Navigating to {self.login_url}")
            assert self.page is not None, "Page initialization failed"
            await self.page.goto(self.login_url, wait_until="networkidle")

            # Wait for page to load
            await asyncio.sleep(2)

            # Try to find and click browsercode option
            # Note: Selectors need to be updated based on actual ASN Bank HTML
            logger.info("🔍 Looking for browsercode login option...")

            browsercode_option_selectors = [
                "button:has-text('Browsercode')",
                "a:has-text('Browsercode')",
                "[data-test*='browsercode']",
                ".browsercode-option",
                "button:has-text('Code')",
                "[class*='browsercode']",
            ]

            clicked_option = False
            for selector in browsercode_option_selectors:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=5000)
                    if element:
                        await element.click()
                        logger.info(
                            f"✅ Clicked browsercode option: {selector}")
                        clicked_option = True
                        break
                except Exception:
                    continue

            if not clicked_option:
                logger.warning(
                    "⚠️ Could not find browsercode option button, proceeding anyway...")

            # Wait for browsercode input field
            await asyncio.sleep(1)

            # Try to find browsercode input field
            logger.info("🔍 Looking for browsercode input field...")

            browsercode_input_selectors = [
                "input[name='browsercode']",
                "input[type='password'][placeholder*='code']",
                "input[id*='browsercode']",
                "input[placeholder*='Browsercode']",
                "input[type='text'][maxlength='5']",
                "input[type='password'][maxlength='5']",
            ]

            input_filled = False
            for selector in browsercode_input_selectors:
                try:
                    input_element = await self.page.wait_for_selector(selector, timeout=5000)
                    if input_element:
                        await input_element.fill(browsercode)
                        logger.info(f"✅ Entered browsercode: {selector}")
                        input_filled = True
                        break
                except Exception:
                    continue

            if not input_filled:
                logger.error("❌ Could not find browsercode input field")
                # Save debug screenshot
                debug_path = "/tmp/asn_browsercode_debug.png"
                await self.page.screenshot(path=debug_path, full_page=True)
                logger.error(f"📸 Debug screenshot saved to {debug_path}")
                return False

            # Try to find and click submit button
            logger.info("🔍 Looking for submit button...")

            submit_selectors = [
                "button[type='submit']",
                "button:has-text('Inloggen')",
                "button:has-text('Login')",
                "input[type='submit']",
                "[data-test*='submit']",
                ".submit-button",
            ]

            clicked_submit = False
            for selector in submit_selectors:
                try:
                    submit_btn = await self.page.wait_for_selector(selector, timeout=5000)
                    if submit_btn:
                        await submit_btn.click()
                        logger.info(f"✅ Clicked submit button: {selector}")
                        clicked_submit = True
                        break
                except Exception:
                    continue

            if not clicked_submit:
                logger.warning(
                    "⚠️ Could not find submit button, trying Enter key...")
                await self.page.keyboard.press("Enter")

            # Wait for login success (redirect to dashboard)
            logger.info("⏳ Waiting for login to complete...")

            try:
                await self.page.wait_for_url("**/overzicht**", timeout=30000)
                logger.info("✅ Browsercode login successful!")

                # Save session for future use
                await self._save_session()

                return True

            except Exception as e:
                logger.error(f"❌ Login failed or timed out: {e}")

                # Check if we're on an error page or still on login
                current_url = self.page.url
                logger.error(f"Current URL: {current_url}")

                # Save debug screenshot
                debug_path = "/tmp/asn_browsercode_error.png"
                await self.page.screenshot(path=debug_path, full_page=True)
                logger.error(f"📸 Error screenshot saved to {debug_path}")

                return False

        except Exception as e:
            logger.error(f"❌ Browsercode login error: {e}")
            return False

    async def is_session_valid(self) -> bool:
        """
        Check if stored session cookies are still valid.

        Returns:
            True if session is valid, False otherwise
        """
        if not os.path.exists(self.session_file):
            return False

        try:
            # Load session and try to access protected page
            await self._load_session()

            if not self.page:
                return False

            # Try to navigate to transactions page
            await self.page.goto(self.transactions_url, wait_until="networkidle", timeout=15000)

            # Check if we're still logged in (not redirected to login page)
            current_url = self.page.url
            if "inloggen" in current_url.lower() or "login" in current_url.lower():
                logger.warning("⚠️ Session expired, redirected to login")
                return False

            logger.info("✅ Session is valid")
            return True

        except Exception as e:
            logger.error(f"❌ Session validation failed: {e}")
            return False

    async def download_transactions(
        self,
        date_from: str,
        date_to: str,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        Download transactions CSV for specified date range.

        Args:
            date_from: Start date in DD-MM-YYYY format
            date_to: End date in DD-MM-YYYY format
            max_retries: Number of retry attempts on failure

        Returns:
            Path to downloaded CSV file, or None on failure
        """
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"📥 Downloading transactions from {date_from} to {date_to} (attempt {attempt + 1}/{max_retries})")

                # Load session if not already loaded
                if not self.page:
                    session_loaded = await self._load_session()
                    if not session_loaded:
                        logger.error("❌ No valid session, please login first")
                        return None

                # Navigate to transactions page
                assert self.page is not None, "Page not initialized"
                await self.page.goto(self.transactions_url, wait_until="networkidle")
                logger.info("📄 On transactions page")

                # Wait for page to fully load
                await asyncio.sleep(2)

                # Set date filters
                # Note: Selectors will need to be updated based on ASN Bank's
                # actual HTML
                try:
                    # Try to find date filter inputs
                    date_from_selector = "input[name*='from'], input[id*='from'], input[placeholder*='van']"
                    date_to_selector = "input[name*='to'], input[id*='to'], input[placeholder*='tot']"

                    await self.page.fill(date_from_selector, date_from)
                    await self.page.fill(date_to_selector, date_to)
                    logger.info(f"📅 Set date range: {date_from} - {date_to}")

                    # Apply filters (usually need to click a button or the form
                    # auto-submits)
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.warning(f"⚠️ Could not set date filters: {e}")
                    # Continue anyway, might download all transactions

                # Setup download listener
                async with self.page.expect_download() as download_info:
                    # Click download/export button
                    # Try multiple possible selectors
                    download_selectors = [
                        "button:has-text('Download')",
                        "button:has-text('Exporteren')",
                        "a:has-text('CSV')",
                        "button:has-text('CSV')",
                        "[data-test*='download']",
                        "[data-test*='export']"
                    ]

                    clicked = False
                    for selector in download_selectors:
                        try:
                            await self.page.click(selector, timeout=5000)
                            clicked = True
                            logger.info(
                                f"✅ Clicked download button: {selector}")
                            break
                        except Exception:
                            continue

                    if not clicked:
                        logger.error("❌ Could not find download button")
                        # Take debug screenshot
                        await self.page.screenshot(path="/tmp/asn_download_debug.png")
                        raise Exception("Download button not found")

                # Wait for download to complete
                download = await download_info.value

                # Generate filename with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"asn_transactions_{timestamp}.csv"
                filepath = os.path.join(self.download_dir, filename)

                # Save the downloaded file
                await download.save_as(filepath)

                logger.info(f"✅ Downloaded CSV to {filepath}")
                return filepath

            except Exception as e:
                logger.error(
                    "❌ Download attempt %d failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.info(f"⏳ Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"❌ All {max_retries} download attempts failed")
                    return None

        return None

    async def cleanup(self) -> None:
        """Close browser and cleanup resources."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            logger.info("✅ Browser cleanup complete")
        except Exception as e:
            logger.error(f"⚠️ Cleanup error: {e}")


# Example usage and testing
async def main():
    """Test the bank scraper."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    scraper = ASNBankScraper()

    # Check if session exists and is valid
    if await scraper.is_session_valid():
        print("✅ Valid session exists")

        # Try to download transactions
        from datetime import datetime, timedelta
        today = datetime.now()
        week_ago = today - timedelta(days=7)

        date_from = week_ago.strftime("%d-%m-%Y")
        date_to = today.strftime("%d-%m-%Y")

        csv_path = await scraper.download_transactions(date_from, date_to)
        if csv_path:
            print(f"✅ Downloaded: {csv_path}")
        else:
            print("❌ Download failed")
    else:
        print("❌ No valid session, starting QR login...")
        success, qr_path = await scraper.login_with_qr()

        if success:
            print("✅ Login successful, session saved")
        else:
            print(f"❌ Login failed: {qr_path}")

    await scraper.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
