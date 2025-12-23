"""
Scraper Utility Module

Provides common utilities for web scraping across all adapters:
- CDP Connection (for ALLDATA, PartsLink24)
- Stealth Mode (for Worldpac, SSF)
- Session Management
- Anti-Detection Measures
"""

import logging
import asyncio
import random
from typing import Optional, Tuple, Literal
from playwright.async_api import async_playwright, Browser, Page, BrowserContext

logger = logging.getLogger(__name__)

# CDP Port for manual Chrome session
CDP_PORT = 9222
CDP_ENDPOINT = f"http://127.0.0.1:{CDP_PORT}"


class ScraperResult:
    """Result container for scraping operations"""
    def __init__(
        self, 
        success: bool, 
        data: any = None, 
        error: str = None,
        requires_manual: bool = False,
        source: str = "unknown"
    ):
        self.success = success
        self.data = data
        self.error = error
        self.requires_manual = requires_manual
        self.source = source


async def get_cdp_connection() -> Tuple[Optional[Browser], Optional[BrowserContext], Optional[Page]]:
    """
    Connect to existing Chrome instance via CDP.
    Used for ALLDATA and PartsLink24 which require persistent sessions.
    
    Returns:
        Tuple of (browser, context, page) or (None, None, None) if connection fails
    """
    try:
        p = await async_playwright().start()
        browser = await p.chromium.connect_over_cdp(CDP_ENDPOINT)
        context = browser.contexts[0]
        page = await context.new_page()
        
        logger.info("CDP connection established successfully")
        return browser, context, page
        
    except Exception as e:
        logger.error(f"CDP connection failed: {e}")
        logger.error("Please run 'start_chrome.bat' and login to vendor sites first!")
        return None, None, None


async def get_stealth_browser() -> Tuple[Optional[Browser], Optional[BrowserContext], Optional[Page]]:
    """
    Launch a new browser instance with stealth settings.
    Used for Worldpac and SSF which have simpler security.
    
    Returns:
        Tuple of (browser, context, page) or (None, None, None) if launch fails
    """
    try:
        from playwright_stealth import stealth_async
        
        p = await async_playwright().start()
        
        # Launch with anti-detection args
        browser = await p.chromium.launch(
            headless=False,  # Headful is less detectable
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-infobars',
                '--window-position=0,0',
                '--ignore-certificate-errors',
                '--ignore-certificate-errors-spki-list',
            ]
        )
        
        # Create context with realistic settings
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/Los_Angeles',
        )
        
        page = await context.new_page()
        
        # Apply stealth patches
        await stealth_async(page)
        
        logger.info("Stealth browser launched successfully")
        return browser, context, page
        
    except ImportError:
        logger.error("playwright-stealth not installed. Run: pip install playwright-stealth")
        return None, None, None
    except Exception as e:
        logger.error(f"Stealth browser launch failed: {e}")
        return None, None, None


async def human_delay(min_ms: int = 500, max_ms: int = 2000):
    """Add human-like random delay between actions"""
    delay = random.randint(min_ms, max_ms)
    await asyncio.sleep(delay / 1000)


async def human_type(page: Page, selector: str, text: str, delay_ms: int = 50):
    """Type text with human-like delays between keystrokes"""
    await page.click(selector)
    await human_delay(200, 500)
    
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.randint(30, delay_ms) / 1000)


async def check_session_status(
    page: Page, 
    site: Literal['alldata', 'partslink', 'worldpac', 'ssf']
) -> bool:
    """
    Check if user is logged in to the specified site.
    
    Args:
        page: Playwright page object
        site: Which vendor site to check
        
    Returns:
        True if logged in, False otherwise
    """
    login_indicators = {
        'alldata': [
            "#vin-search",           # VIN search box
            ".dashboard",            # Dashboard element
            "[data-testid='search']" # Search component
        ],
        'partslink': [
            "#vin_input",            # VIN input field
            ".main_menu",            # Main menu
            "#search-form"           # Search form
        ],
        'worldpac': [
            ".dashboard",            # Dashboard
            "#part-search-input",    # Part search
            ".user-menu"             # User menu (logged in)
        ],
        'ssf': [
            "#search",               # Search box
            "input[name='search']",  # Search input
            ".account-menu"          # Account menu
        ]
    }
    
    selectors = login_indicators.get(site, [])
    
    for selector in selectors:
        try:
            is_visible = await page.is_visible(selector)
            if is_visible:
                logger.info(f"{site.upper()}: Session valid (found {selector})")
                return True
        except Exception:
            continue
    
    logger.warning(f"{site.upper()}: Session appears invalid or expired")
    return False


async def safe_navigate(page: Page, url: str, wait_until: str = "domcontentloaded") -> bool:
    """
    Safely navigate to a URL with error handling.
    
    Returns:
        True if navigation successful, False otherwise
    """
    try:
        await human_delay(300, 800)
        await page.goto(url, wait_until=wait_until, timeout=30000)
        await human_delay(500, 1500)
        return True
    except Exception as e:
        logger.error(f"Navigation to {url} failed: {e}")
        return False


async def safe_click(page: Page, selector: str, timeout: int = 10000) -> bool:
    """Safely click an element with error handling"""
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        await human_delay(200, 500)
        await page.click(selector)
        return True
    except Exception as e:
        logger.error(f"Click on {selector} failed: {e}")
        return False


async def safe_fill(page: Page, selector: str, value: str, timeout: int = 10000) -> bool:
    """Safely fill an input with error handling"""
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        await human_delay(200, 400)
        await page.fill(selector, value)
        return True
    except Exception as e:
        logger.error(f"Fill on {selector} failed: {e}")
        return False


async def take_debug_screenshot(page: Page, name: str):
    """Take a screenshot for debugging purposes"""
    try:
        filename = f"{name}.png"
        await page.screenshot(path=filename)
        logger.info(f"Debug screenshot saved: {filename}")
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")


class ScraperMode:
    """Enum-like class for scraper modes"""
    CDP = "cdp"           # Connect to existing Chrome (ALLDATA, PartsLink)  
    STEALTH = "stealth"   # Launch new browser with stealth (Worldpac, SSF)
    MOCK = "mock"         # Return mock data (fallback)


# Site-specific configurations
SITE_CONFIG = {
    'alldata': {
        'mode': ScraperMode.CDP,
        'base_url': 'https://my.alldata.com',
        'login_url': 'https://my.alldata.com/login',
    },
    'partslink': {
        'mode': ScraperMode.CDP,
        'base_url': 'https://www.partslink24.com/partslink24/p5.do',
        'login_url': 'https://www.partslink24.com/partslink24/user/login.do',
    },
    'worldpac': {
        'mode': ScraperMode.STEALTH,
        'base_url': 'https://speeddial.worldpac.com',
        'login_url': 'https://speeddial.worldpac.com/login',
    },
    'ssf': {
        'mode': ScraperMode.STEALTH,
        'base_url': 'https://shop.ssfautoparts.com',
        'login_url': 'https://shop.ssfautoparts.com',
    }
}


def get_site_config(site: str) -> dict:
    """Get configuration for a specific site"""
    return SITE_CONFIG.get(site, {})
