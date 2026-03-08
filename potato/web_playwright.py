"""
Playwright Fallback for Web Agent Recording

Server-side headless browser for sites that block iframe embedding.
Uses Playwright to render pages and stream screenshots back to the client.

This is an optional dependency - only imported when needed.
Install with: pip install playwright && playwright install chromium

Usage:
    session = PlaywrightSession()
    await session.start("https://example.com")
    screenshot_bytes = await session.screenshot()
    await session.click(100, 200)
    await session.stop()
"""

import asyncio
import logging
import os
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class PlaywrightSession:
    """
    Manages a headless browser session for web agent recording.

    Each session runs a Chromium instance that navigates pages,
    captures screenshots, and executes user interactions.
    """

    def __init__(self, width: int = 1280, height: int = 720):
        self.width = width
        self.height = height
        self.browser = None
        self.context = None
        self.page = None
        self._playwright = None

    async def start(self, url: str) -> bool:
        """Launch browser and navigate to URL."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright is not installed. Install with: "
                "pip install playwright && playwright install chromium"
            )
            return False

        try:
            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context(
                viewport={"width": self.width, "height": self.height},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self.page = await self.context.new_page()
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            logger.info(f"Playwright session started at {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to start Playwright session: {e}")
            await self.stop()
            return False

    async def screenshot(self) -> Optional[bytes]:
        """Capture current page screenshot as PNG bytes."""
        if not self.page:
            return None
        try:
            return await self.page.screenshot(type="png")
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None

    async def click(self, x: int, y: int) -> bool:
        """Execute click at coordinates."""
        if not self.page:
            return False
        try:
            await self.page.mouse.click(x, y)
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            return True
        except Exception as e:
            logger.warning(f"Click failed at ({x}, {y}): {e}")
            return False

    async def type_text(self, text: str) -> bool:
        """Type text into the currently focused element."""
        if not self.page:
            return False
        try:
            await self.page.keyboard.type(text)
            return True
        except Exception as e:
            logger.warning(f"Type failed: {e}")
            return False

    async def scroll(self, dx: int = 0, dy: int = 0) -> bool:
        """Scroll the page."""
        if not self.page:
            return False
        try:
            await self.page.mouse.wheel(dx, dy)
            return True
        except Exception as e:
            logger.warning(f"Scroll failed: {e}")
            return False

    async def navigate(self, url: str) -> bool:
        """Navigate to a new URL."""
        if not self.page:
            return False
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return True
        except Exception as e:
            logger.warning(f"Navigation failed to {url}: {e}")
            return False

    async def get_state(self) -> Dict[str, Any]:
        """Get current page state."""
        if not self.page:
            return {}
        try:
            return {
                "url": self.page.url,
                "title": await self.page.title(),
                "viewport": {"width": self.width, "height": self.height},
            }
        except Exception:
            return {}

    async def stop(self):
        """Close browser and clean up."""
        try:
            if self.browser:
                await self.browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
        finally:
            self.browser = None
            self.context = None
            self.page = None
            self._playwright = None


def check_playwright_available() -> bool:
    """Check if Playwright is installed and has browsers."""
    try:
        import playwright
        return True
    except ImportError:
        return False
