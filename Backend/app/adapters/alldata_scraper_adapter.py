"""
ALLDATA Scraper Adapter - CDP Connection Implementation

Uses Chrome DevTools Protocol to connect to an existing Chrome session.
User must manually login to ALLDATA first via start_chrome.bat.

This is part of the Hybrid Approach:
- ALLDATA/PartsLink24: CDP + Manual Login (this file)
- Worldpac/SSF: Stealth Mode
"""

import logging
from typing import Optional
from decimal import Decimal
from app.adapters.labor_adapter_interface import LaborAdapterInterface, LaborTimeResult
from app.core.config import settings

logger = logging.getLogger(__name__)


class AlldataScraperAdapter(LaborAdapterInterface):
    """
    Real implementation using Playwright CDP connection for ALLDATA.
    Requires manual Chrome session with active ALLDATA login.
    """

    async def get_labor_time(self, vin: str, job_description: str) -> Optional[LaborTimeResult]:
        logger.info(f"ALLDATA SCRAPER: Fetching labor for VIN={vin}, Job={job_description}")
        
        # Check credentials
        if not settings.ALLDATA_USERNAME or not settings.ALLDATA_PASSWORD:
            logger.error("ALLDATA SCRAPER: Missing credentials!")
            return await self._get_fallback_data(job_description)
        
        try:
            from app.utils.scraper_utils import (
                get_cdp_connection,
                human_delay,
                safe_navigate,
                safe_fill,
                safe_click,
                take_debug_screenshot,
                check_session_status
            )
            
            browser, context, page = await get_cdp_connection()
            
            if not browser:
                logger.error("ALLDATA: CDP connection failed. Run start_chrome.bat first!")
                return await self._get_fallback_data(job_description)
            
            try:
                # Navigate to ALLDATA
                if not await safe_navigate(page, "https://my.alldata.com"):
                    raise Exception("Failed to navigate to ALLDATA")
                
                # Check login status
                is_logged_in = await check_session_status(page, 'alldata')
                
                if not is_logged_in:
                    logger.info("ALLDATA: Not logged in. Attempting auto-login...")
                    
                    try:
                        # Wait for login form
                        await page.wait_for_selector(
                            "input[autocomplete='username'], #username, input[name='username']", 
                            timeout=10000
                        )
                        
                        # Fill credentials
                        username_selectors = ["#username", "input[name='username']", "input[autocomplete='username']"]
                        for sel in username_selectors:
                            try:
                                if await page.is_visible(sel):
                                    await page.fill(sel, settings.ALLDATA_USERNAME)
                                    break
                            except:
                                continue
                        
                        await human_delay(300, 600)
                        
                        # Password
                        password_selectors = ["#password", "input[name='password']", "input[type='password']"]
                        for sel in password_selectors:
                            try:
                                if await page.is_visible(sel):
                                    await page.fill(sel, settings.ALLDATA_PASSWORD)
                                    break
                            except:
                                continue
                        
                        await human_delay(300, 600)
                        
                        # Click login
                        await safe_click(page, "#login-btn, button[type='submit'], .login-button")
                        
                        # Wait for dashboard
                        await page.wait_for_selector(".dashboard, #main-content", timeout=60000)
                        logger.info("ALLDATA: Login successful!")
                        
                    except Exception as login_err:
                        logger.warning(f"ALLDATA: Auto-login failed ({login_err}). Please login manually.")
                        await take_debug_screenshot(page, "alldata_login_fail")
                
                # VIN Search
                try:
                    await human_delay(500, 1000)
                    
                    # Wait for search input
                    vin_selectors = ["#vin-search", "input[name='vin']", "#vin-input", ".vin-search-input"]
                    
                    vin_filled = False
                    for vin_sel in vin_selectors:
                        try:
                            await page.wait_for_selector(vin_sel, timeout=10000)
                            await page.fill(vin_sel, "")
                            await human_delay(200, 400)
                            await page.fill(vin_sel, vin)
                            vin_filled = True
                            logger.info(f"ALLDATA: Filled VIN using {vin_sel}")
                            break
                        except:
                            continue
                    
                    if not vin_filled:
                        raise Exception("Could not find VIN search input")
                    
                    # Click search
                    search_btn_selectors = ["#search-btn", "button.search", "#vin-search-btn", "[type='submit']"]
                    for btn_sel in search_btn_selectors:
                        try:
                            if await page.is_visible(btn_sel):
                                await page.click(btn_sel)
                                break
                        except:
                            continue
                    
                    # Wait for vehicle results
                    await human_delay(2000, 4000)
                    
                    # Now search for the job/operation
                    # This is simplified - real ALLDATA has complex navigation
                    
                    # Try to find labor time in the interface
                    labor_time = None
                    labor_selectors = [
                        ".labor-time", 
                        ".time-value",
                        "[data-labor-time]",
                        ".hours"
                    ]
                    
                    for labor_sel in labor_selectors:
                        try:
                            if await page.is_visible(labor_sel):
                                time_text = await page.inner_text(labor_sel)
                                import re
                                time_match = re.search(r'(\d+\.?\d*)', time_text)
                                if time_match:
                                    labor_time = Decimal(time_match.group(1))
                                    break
                        except:
                            continue
                    
                    if not labor_time:
                        # Default fallback time based on job type
                        labor_time = self._estimate_labor_time(job_description)
                        logger.warning(f"ALLDATA: Could not scrape labor time, using estimate: {labor_time}h")
                    
                    # Close the tab (not browser)
                    await page.close()
                    
                    return LaborTimeResult(
                        jobDescription=job_description,
                        laborHours=labor_time,
                        source="alldata-scraped" if labor_time else "alldata-estimated",
                        category="Scraped",
                        difficulty="Medium"
                    )
                    
                except Exception as search_err:
                    curr_url = page.url
                    await take_debug_screenshot(page, "alldata_search_fail")
                    logger.error(f"ALLDATA SEARCH FAILED. URL: {curr_url}, Error: {search_err}")
                    raise
                    
            finally:
                # Don't close browser - keep session alive
                try:
                    await page.close()
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"ALLDATA SCRAPER ERROR: {e}")
            return await self._get_fallback_data(job_description)

    def _estimate_labor_time(self, job_description: str) -> Decimal:
        """Estimate labor time based on job description keywords"""
        job_lower = job_description.lower()
        
        # Common job time estimates
        estimates = {
            'brake pad': Decimal('1.2'),
            'brake rotor': Decimal('2.0'),
            'oil change': Decimal('0.5'),
            'spark plug': Decimal('1.5'),
            'battery': Decimal('0.3'),
            'alternator': Decimal('1.5'),
            'starter': Decimal('1.8'),
            'water pump': Decimal('3.0'),
            'timing belt': Decimal('4.5'),
            'transmission fluid': Decimal('1.0'),
            'ac compressor': Decimal('3.5'),
            'strut': Decimal('2.5'),
            'shock': Decimal('1.5'),
            'tie rod': Decimal('1.2'),
            'ball joint': Decimal('2.0'),
            'wheel bearing': Decimal('2.5'),
        }
        
        for keyword, hours in estimates.items():
            if keyword in job_lower:
                return hours
        
        # Default estimate
        return Decimal('1.5')

    async def _get_fallback_data(self, job_description: str) -> LaborTimeResult:
        """Return fallback data when scraping fails"""
        estimated_hours = self._estimate_labor_time(job_description)
        
        return LaborTimeResult(
            jobDescription=f"{job_description} (⚠️ MANUAL VERIFICATION NEEDED)",
            laborHours=estimated_hours,
            source="alldata-fallback",
            category="Estimated - Check ALLDATA",
            difficulty="Unknown"
        )

    # Keep old method for backwards compatibility
    async def _simulate_live_scrape(self, vin: str, job_description: str) -> LaborTimeResult:
        return await self._get_fallback_data(job_description)
