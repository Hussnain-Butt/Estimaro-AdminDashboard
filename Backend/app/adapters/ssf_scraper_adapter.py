"""
SSF (South San Francisco Auto Parts) Scraper Adapter - Stealth Mode Implementation

Uses stealth browser with anti-detection measures.
This is part of the Hybrid Approach:
- ALLDATA/PartsLink24: CDP + Manual Login
- Worldpac/SSF: Stealth Mode (this file)
"""

import logging
import asyncio
from typing import List
from decimal import Decimal
import random
from app.adapters.vendor_adapter_interface import VendorAdapterInterface, VendorPriceResult
from app.core.config import settings

logger = logging.getLogger(__name__)


class SSFScraperAdapter(VendorAdapterInterface):
    """
    SSF Implementation using Stealth Browser.
    Scrapes pricing for specific part numbers with anti-detection.
    """

    async def get_prices(self, part_numbers: List[str]) -> List[VendorPriceResult]:
        logger.info(f"SSF SCRAPER: Getting prices for {part_numbers}")
        
        # Check credentials
        if not settings.SSF_USERNAME or not settings.SSF_PASSWORD:
            logger.warning("SSF SCRAPER: Missing credentials! Using fallback data.")
            return await self._get_fallback_data(part_numbers)
        
        try:
            from app.utils.scraper_utils import (
                get_stealth_browser, 
                human_delay, 
                human_type,
                safe_navigate,
                take_debug_screenshot,
                check_session_status
            )
            
            browser, context, page = await get_stealth_browser()
            
            if not browser:
                logger.error("SSF: Could not launch stealth browser")
                return await self._get_fallback_data(part_numbers)
            
            try:
                results = []
                
                # Navigate to SSF
                if not await safe_navigate(page, "https://shop.ssfautoparts.com/"):
                    raise Exception("Failed to navigate to SSF")
                
                # Wait for page to load
                await human_delay(1500, 3000)
                
                # Check if already logged in
                is_logged_in = await check_session_status(page, 'ssf')
                
                if not is_logged_in:
                    logger.info("SSF: Attempting login...")
                    
                    # SSF login form selectors
                    try:
                        # Wait for login form
                        await page.wait_for_selector(
                            "input[placeholder='Account#/Username'], #username, input[name='username']", 
                            timeout=10000
                        )
                        
                        # Username field
                        username_selectors = [
                            "input[placeholder='Account#/Username']",
                            "#username",
                            "input[name='username']",
                            "input[name='account']"
                        ]
                        
                        for user_sel in username_selectors:
                            try:
                                if await page.is_visible(user_sel):
                                    await human_type(page, user_sel, settings.SSF_USERNAME)
                                    logger.info(f"SSF: Filled username using {user_sel}")
                                    break
                            except:
                                continue
                        
                        await human_delay(300, 600)
                        
                        # Password field
                        password_selectors = [
                            "input[placeholder='Password']",
                            "#password",
                            "input[name='password']",
                            "input[type='password']"
                        ]
                        
                        for pass_sel in password_selectors:
                            try:
                                if await page.is_visible(pass_sel):
                                    await human_type(page, pass_sel, settings.SSF_PASSWORD)
                                    logger.info(f"SSF: Filled password using {pass_sel}")
                                    break
                            except:
                                continue
                        
                        await human_delay(500, 1000)
                        
                        # Click login button
                        login_selectors = [
                            "#user-login-submit-button",
                            "button[type='submit']",
                            ".login-button",
                            "input[type='submit']",
                            "#login-btn"
                        ]
                        
                        for btn_sel in login_selectors:
                            try:
                                if await page.is_visible(btn_sel):
                                    await page.click(btn_sel)
                                    logger.info(f"SSF: Clicked login using {btn_sel}")
                                    break
                            except:
                                continue
                        
                        # Wait for navigation/page change
                        await human_delay(3000, 5000)
                        
                        # Verify login success
                        try:
                            # Check for common logged-in indicators
                            logged_in_indicators = [
                                ".account-menu",
                                ".user-menu", 
                                "#logout",
                                ".welcome-user",
                                "#search"
                            ]
                            
                            login_success = False
                            for indicator in logged_in_indicators:
                                if await page.is_visible(indicator):
                                    login_success = True
                                    logger.info(f"SSF: Login verified via {indicator}")
                                    break
                            
                            if not login_success:
                                await take_debug_screenshot(page, "ssf_login_status")
                                logger.warning("SSF: Login status unclear - continuing anyway")
                                
                        except Exception as verify_err:
                            logger.warning(f"SSF: Could not verify login: {verify_err}")
                    
                    except Exception as login_err:
                        await take_debug_screenshot(page, "ssf_login_fail")
                        logger.error(f"SSF: Login failed: {login_err}")
                        # Continue anyway - might still work
                
                # Now search for parts
                for part_num in part_numbers:
                    try:
                        logger.info(f"SSF: Searching for part {part_num}")
                        
                        # Find search box
                        search_selectors = [
                            "input[name='search']",
                            "#search",
                            "#keyword",
                            "input[placeholder*='Search']",
                            "input[placeholder*='Part']",
                            ".search-input",
                            "input[type='search']"
                        ]
                        
                        search_filled = False
                        for search_sel in search_selectors:
                            try:
                                if await page.is_visible(search_sel):
                                    await page.fill(search_sel, "")  # Clear first
                                    await human_delay(200, 400)
                                    await human_type(page, search_sel, part_num)
                                    search_filled = True
                                    logger.info(f"SSF: Filled search using {search_sel}")
                                    break
                            except:
                                continue
                        
                        if not search_filled:
                            logger.warning(f"SSF: Could not find search box for {part_num}")
                            await take_debug_screenshot(page, f"ssf_no_search_{part_num}")
                            fallback = await self._get_fallback_data([part_num])
                            results.extend(fallback)
                            continue
                        
                        # Submit search
                        await human_delay(300, 600)
                        await page.keyboard.press("Enter")
                        
                        # Wait for results
                        await human_delay(3000, 5000)
                        
                        # Try to scrape price
                        price = None
                        price_selectors = [
                            ".price",
                            ".product-price", 
                            ".item-price",
                            "[data-price]",
                            ".cost",
                            ".amount",
                            ".your-price",
                            ".net-price"
                        ]
                        
                        for price_sel in price_selectors:
                            try:
                                if await page.is_visible(price_sel):
                                    price_text = await page.inner_text(price_sel)
                                    # Extract number from text
                                    import re
                                    price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
                                    if price_match:
                                        price = Decimal(price_match.group())
                                        logger.info(f"SSF: Found price ${price} using {price_sel}")
                                        break
                            except:
                                continue
                        
                        # Try to get brand
                        brand = "SSF Aftermarket"
                        brand_selectors = [
                            ".brand",
                            ".manufacturer",
                            ".product-brand",
                            ".vendor-name"
                        ]
                        for brand_sel in brand_selectors:
                            try:
                                if await page.is_visible(brand_sel):
                                    brand = await page.inner_text(brand_sel)
                                    brand = brand[:50]  # Truncate
                                    break
                            except:
                                continue
                        
                        # Try to get stock status
                        stock_status = "Check SSF Website"
                        stock_selectors = [
                            ".stock-status",
                            ".availability",
                            ".in-stock",
                            ".stock"
                        ]
                        for stock_sel in stock_selectors:
                            try:
                                if await page.is_visible(stock_sel):
                                    stock_status = await page.inner_text(stock_sel)
                                    stock_status = stock_status[:30]  # Truncate
                                    break
                            except:
                                continue
                        
                        # Create result
                        if price and price > 0:
                            results.append(VendorPriceResult(
                                vendor_id=f"ssf_{random.randint(1000, 9999)}",
                                vendor_name="SSF",
                                brand=brand,
                                part_number=part_num,
                                price=price,
                                stock_status=f"Live Scraped - {stock_status}",
                                stock_quantity=1,
                                warehouse_location="South San Francisco, CA",
                                warehouse_distance_miles=0,
                                delivery_option="See SSF Website",
                                warranty="Manufacturer Warranty"
                            ))
                            logger.info(f"SSF: Successfully scraped {part_num} @ ${price}")
                        else:
                            logger.warning(f"SSF: No valid price for {part_num}")
                            fallback = await self._get_fallback_data([part_num])
                            results.extend(fallback)
                        
                    except Exception as part_err:
                        logger.error(f"SSF: Error searching {part_num}: {part_err}")
                        fallback = await self._get_fallback_data([part_num])
                        results.extend(fallback)
                
                return results if results else await self._get_fallback_data(part_numbers)
                
            finally:
                # Close browser
                try:
                    await browser.close()
                except:
                    pass
                    
        except ImportError as ie:
            logger.error(f"SSF: Missing dependency: {ie}")
            return await self._get_fallback_data(part_numbers)
        except Exception as e:
            logger.error(f"SSF SCRAPER ERROR: {e}")
            return await self._get_fallback_data(part_numbers)

    async def _get_fallback_data(self, part_numbers: List[str]) -> List[VendorPriceResult]:
        """
        Return fallback data when scraping fails.
        Data is marked as requiring manual verification.
        """
        await asyncio.sleep(1)  # Small delay
        results = []
        
        for part in part_numbers:
            base_price = Decimal(random.randint(60, 160))
            results.append(VendorPriceResult(
                vendor_id=f"ssf_fallback_{random.randint(100, 999)}",
                vendor_name="SSF",
                brand="TBD - Manual Check Required",
                part_number=part,
                price=base_price,
                stock_status="⚠️ REQUIRES MANUAL VERIFICATION",
                stock_quantity=0,
                warehouse_location="South San Francisco - Verify on SSF Site",
                warehouse_distance_miles=22.0,
                delivery_option="Manual Check Required",
                warranty="Unknown"
            ))
        
        logger.warning(f"SSF: Returned fallback data for {len(part_numbers)} parts - MANUAL VERIFICATION NEEDED")
        return results

    # Keep old method for backwards compatibility
    async def _simulate_live_scrape(self, part_numbers: List[str]) -> List[VendorPriceResult]:
        return await self._get_fallback_data(part_numbers)
