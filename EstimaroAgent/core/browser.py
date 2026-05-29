"""Connects to an already-running Chrome (started in remote-debug mode).
Reuses your logged-in sessions for ALLDATA, PartsLink24, SSF, etc."""
from pathlib import Path
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from loguru import logger

from config import settings


class ChromeDebugBrowser:
    """Async wrapper around Playwright connected to existing Chrome."""

    def __init__(self):
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)
        if not self.browser.contexts:
            raise RuntimeError(
                "No Chrome context found. Run start_chrome_debug.bat first and open at least one tab."
            )
        self.context = self.browser.contexts[0]
        logger.info(f"Connected to Chrome at {settings.chrome_cdp_url}")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._playwright:
            await self._playwright.stop()

    async def find_tab_by_url(self, url_substring: str) -> Optional[Page]:
        for page in self.context.pages:
            if url_substring.lower() in page.url.lower():
                return page
        return None

    async def open_or_focus(self, url: str, url_match: Optional[str] = None) -> Page:
        match_str = url_match or url.split("/")[2]
        existing = await self.find_tab_by_url(match_str)
        if existing:
            await existing.bring_to_front()
            return existing
        page = await self.context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        return page

    async def screenshot(self, page: Page, label: str = "shot") -> tuple[bytes, str]:
        Path(settings.SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = Path(settings.SCREENSHOT_DIR) / f"{label}_{ts}.png"
        data = await page.screenshot(full_page=False)
        path.write_bytes(data)
        return data, str(path)


async def _smoke_test():
    print("Connecting to Chrome debug...")
    async with ChromeDebugBrowser() as cb:
        print(f"Open tabs: {len(cb.context.pages)}")
        for i, p in enumerate(cb.context.pages):
            print(f"  [{i}] {p.url}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_smoke_test())
