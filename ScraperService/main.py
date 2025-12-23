"""
Estimaro Scraper Microservice

This service runs on the Windows RDP server where Chrome is logged into
vendor websites (ALLDATA, PartsLink24, Worldpac, SSF).

The main backend (deployed anywhere) calls this service via HTTP API
to get scraped data from vendor sites.

Endpoints:
  POST /scrape/labor     - Get labor time from ALLDATA
  POST /scrape/parts     - Get OEM parts from PartsLink24
  POST /scrape/pricing   - Get pricing from Worldpac/SSF
  GET  /health           - Health check
"""

import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
API_KEY = os.getenv("SCRAPER_API_KEY", "estimaro_scraper_secret_2024")
CDP_PORT = 9222

app = FastAPI(
    title="Estimaro Scraper Service",
    description="Microservice for scraping vendor websites via Chrome CDP",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# API KEY AUTHENTICATION
# =============================================================================
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================
class LaborRequest(BaseModel):
    vin: str
    job_description: str


class LaborResponse(BaseModel):
    success: bool
    labor_hours: Optional[float] = None
    job_description: str
    source: str
    error: Optional[str] = None


class PartsRequest(BaseModel):
    vin: str
    job_description: str


class PartItem(BaseModel):
    part_number: str
    description: str
    manufacturer: str
    is_oem: bool


class PartsResponse(BaseModel):
    success: bool
    parts: List[PartItem] = []
    source: str
    error: Optional[str] = None


class PricingRequest(BaseModel):
    part_numbers: List[str]


class PriceItem(BaseModel):
    vendor: str
    part_number: str
    brand: str
    price: float
    stock_status: str
    warehouse: str


class PricingResponse(BaseModel):
    success: bool
    prices: List[PriceItem] = []
    source: str
    error: Optional[str] = None


# =============================================================================
# SCRAPING FUNCTIONS
# =============================================================================
async def get_existing_page_for_site(target_url_contains: str):
    """
    Find an existing page/tab where the target site is already open and logged in.
    This uses the same session cookies as the manually logged-in tabs.
    """
    from playwright.async_api import async_playwright
    
    try:
        p = await async_playwright().start()
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        context = browser.contexts[0]
        
        # Get all open pages/tabs
        pages = context.pages
        logger.info(f"Found {len(pages)} open tabs in Chrome")
        
        # Find a page that contains our target URL
        for page in pages:
            current_url = page.url
            logger.info(f"Tab URL: {current_url}")
            if target_url_contains.lower() in current_url.lower():
                logger.info(f"Found matching tab for {target_url_contains}")
                return browser, page, False  # False = don't close this page
        
        # If no existing tab found, create new page (will inherit cookies from context)
        logger.info(f"No existing tab for {target_url_contains}, creating new page with existing cookies")
        new_page = await context.new_page()
        return browser, new_page, True  # True = close this page when done
        
    except Exception as e:
        logger.error(f"CDP connection failed: {e}")
        raise HTTPException(
            status_code=503, 
            detail=f"Chrome not running or not in debug mode. Error: {str(e)}"
        )


# =============================================================================
# DOM DISCOVERY - Auto-find elements on page
# =============================================================================
async def discover_page_elements(page, element_type: str = "all") -> dict:
    """
    Scan page and discover all relevant elements for debugging.
    Returns dict with found elements and suggested selectors.
    
    element_type: "input", "button", "price", "link", or "all"
    """
    discovered = {
        "inputs": [],
        "buttons": [],
        "prices": [],
        "links": [],
        "tables": [],
        "suggested_selectors": []
    }
    
    try:
        logger.info("🔍 DOM DISCOVERY: Scanning page for elements...")
        
        # Discover INPUT elements
        if element_type in ["input", "all"]:
            inputs = await page.query_selector_all("input, textarea")
            for inp in inputs[:20]:  # Max 20
                try:
                    attrs = {
                        "id": await inp.get_attribute("id"),
                        "name": await inp.get_attribute("name"),
                        "class": await inp.get_attribute("class"),
                        "placeholder": await inp.get_attribute("placeholder"),
                        "type": await inp.get_attribute("type"),
                        "value": await inp.get_attribute("value")
                    }
                    # Filter out empty
                    attrs = {k: v for k, v in attrs.items() if v}
                    if attrs:
                        discovered["inputs"].append(attrs)
                        # Generate selector suggestion
                        if attrs.get("id"):
                            discovered["suggested_selectors"].append(f"#{attrs['id']}")
                        elif attrs.get("placeholder"):
                            discovered["suggested_selectors"].append(f"input[placeholder*='{attrs['placeholder'][:20]}']")
                        elif attrs.get("name"):
                            discovered["suggested_selectors"].append(f"input[name='{attrs['name']}']")
                except:
                    continue
        
        # Discover BUTTON elements
        if element_type in ["button", "all"]:
            buttons = await page.query_selector_all("button, input[type='submit'], a.btn, div.btn, .button")
            for btn in buttons[:15]:
                try:
                    text = await btn.inner_text()
                    attrs = {
                        "text": text[:50] if text else None,
                        "id": await btn.get_attribute("id"),
                        "class": await btn.get_attribute("class"),
                        "type": await btn.get_attribute("type")
                    }
                    attrs = {k: v for k, v in attrs.items() if v}
                    if attrs:
                        discovered["buttons"].append(attrs)
                        if attrs.get("text"):
                            discovered["suggested_selectors"].append(f"text={attrs['text'][:20]}")
                except:
                    continue
        
        # Discover PRICE elements (numbers with $ or decimal)
        if element_type in ["price", "all"]:
            import re
            spans = await page.query_selector_all("span, td, div.price, .amount, .value")
            for sp in spans[:30]:
                try:
                    text = await sp.inner_text()
                    if text and re.search(r'\$?\d+\.?\d*', text):
                        price_match = re.search(r'\$?([\d,]+\.?\d*)', text)
                        if price_match:
                            val = float(price_match.group(1).replace(',', ''))
                            if 0 < val < 50000:  # Reasonable price/hours range
                                cls = await sp.get_attribute("class")
                                discovered["prices"].append({
                                    "value": text[:30],
                                    "class": cls,
                                    "tag": await sp.evaluate("el => el.tagName")
                                })
                                if cls:
                                    discovered["suggested_selectors"].append(f".{cls.split()[0]}")
                except:
                    continue
        
        # Discover LINK elements
        if element_type in ["link", "all"]:
            links = await page.query_selector_all("a[href]")
            for link in links[:15]:
                try:
                    text = await link.inner_text()
                    href = await link.get_attribute("href")
                    if text and len(text) > 2:
                        discovered["links"].append({
                            "text": text[:40],
                            "href": href[:60] if href else None
                        })
                        if text:
                            discovered["suggested_selectors"].append(f"text={text[:20]}")
                except:
                    continue
        
        # Log discovered elements
        logger.info(f"🔍 DISCOVERED: {len(discovered['inputs'])} inputs, {len(discovered['buttons'])} buttons, {len(discovered['prices'])} prices, {len(discovered['links'])} links")
        
        # Log detailed info
        if discovered["inputs"]:
            logger.info("📝 INPUTS FOUND:")
            for i, inp in enumerate(discovered["inputs"][:5]):
                logger.info(f"   {i+1}. {inp}")
        
        if discovered["buttons"]:
            logger.info("🔘 BUTTONS FOUND:")
            for i, btn in enumerate(discovered["buttons"][:5]):
                logger.info(f"   {i+1}. {btn}")
        
        if discovered["prices"]:
            logger.info("💰 PRICES/NUMBERS FOUND:")
            for i, price in enumerate(discovered["prices"][:5]):
                logger.info(f"   {i+1}. {price}")
        
        if discovered["suggested_selectors"]:
            logger.info("💡 SUGGESTED SELECTORS:")
            for sel in discovered["suggested_selectors"][:10]:
                logger.info(f"   → {sel}")
        
        return discovered
        
    except Exception as e:
        logger.error(f"DOM Discovery error: {e}")
        return discovered

async def scrape_alldata_labor(vin: str, job_description: str) -> dict:
    """
    FULL AUTOMATION: Scrape labor time from ALLDATA
    Flow: Home → REPAIR → VIN Search → Parts & Labor → Job Search → Extract Hours
    """
    logger.info(f"ALLDATA: Full automation for VIN={vin}, Job={job_description}")
    
    browser, page, should_close = await get_existing_page_for_site("alldata")
    
    try:
        import re
        current_url = page.url.lower()
        
        # Step 1: Check if logged in
        if "alldata" not in current_url:
            await page.goto("https://my.alldata.com", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            current_url = page.url.lower()
        
        is_logged_in = "alldata" in current_url and not any(x in current_url for x in ["/login", "/signin", "/auth", "authn"])
        if any(x in current_url for x in ["/migrate", "/home", "/dashboard", "#/"]):
            is_logged_in = True
        
        logger.info(f"ALLDATA URL: {current_url}, Logged in: {is_logged_in}")
        
        if not is_logged_in:
            return {"success": False, "error": "Not logged into ALLDATA. Please login in Chrome first."}
        
        # Step 2: Navigate to REPAIR section if on home
        repair_clicked = False
        if "/home" in current_url or current_url.endswith("alldata.com/"):
            logger.info("ALLDATA: On home page, waiting for REPAIR button...")
            await asyncio.sleep(2)  # Wait for page to fully load
            
            try:
                # Try multiple selectors for REPAIR button - REAL SELECTORS
                repair_selectors = [
                    ".alldata-icon-appIcon-repair",  # REAL selector from DevTools
                    "div.alldata-icon-appIcon-repair",
                    "[icon-title='ALLDATA Repair']",
                    "div[ng-click*='selectProduct']"
                ]
                
                for sel in repair_selectors:
                    try:
                        logger.info(f"ALLDATA: Trying selector: {sel}")
                        el = await page.query_selector(sel)
                        if el:
                            # Check if element is visible
                            is_visible = await el.is_visible()
                            logger.info(f"ALLDATA: Found element with {sel}, visible={is_visible}")
                            if is_visible:
                                await el.click()
                                await asyncio.sleep(3)
                                repair_clicked = True
                                logger.info(f"ALLDATA: ✅ Clicked REPAIR using {sel}")
                                break
                        else:
                            logger.info(f"ALLDATA: Selector {sel} - no element found")
                    except Exception as e:
                        logger.warning(f"ALLDATA: Selector {sel} failed: {e}")
                        continue
                        
                if not repair_clicked:
                    logger.warning("ALLDATA: REPAIR click failed, navigating directly to repair page")
                    
            except Exception as e:
                logger.warning(f"ALLDATA: Could not click REPAIR: {e}")
        
        # Step 3: Navigate to Select Vehicle page (if REPAIR click failed or already there)
        current_url = page.url.lower()
        if "select-vehicle" not in current_url and "repair" not in current_url:
            logger.info("ALLDATA: Navigating directly to select-vehicle page...")
            await page.goto("https://my.alldata.com/migrate/repair/#/select-vehicle", wait_until="domcontentloaded")
            await asyncio.sleep(2)
        
        # Step 4: Enter VIN and search
        logger.info("ALLDATA: Entering VIN...")
        vin_selectors = ["#ymmeSearchBox", "input[placeholder*='VIN']", "input[placeholder*='Search']"]
        vin_entered = False
        
        for sel in vin_selectors:
            try:
                if await page.is_visible(sel):
                    await page.fill(sel, "")  # Clear first
                    await page.fill(sel, vin)
                    await page.keyboard.press("Enter")
                    vin_entered = True
                    logger.info(f"ALLDATA: VIN entered using {sel}")
                    break
            except:
                continue
        
        if not vin_entered:
            return {"success": False, "error": "Could not find VIN search box in ALLDATA"}
        
        await asyncio.sleep(3)  # Wait for vehicle to load
        
        # Step 5: Click on Parts and Labor
        logger.info("ALLDATA: Looking for Parts and Labor...")
        parts_labor_clicked = False
        parts_labor_selectors = [
            "text=Parts and Labor",
            "a:has-text('Parts and Labor')",
            ".parts-labor-link",
            "[data-testid='parts-labor']"
        ]
        
        for sel in parts_labor_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    parts_labor_clicked = True
                    logger.info(f"ALLDATA: Clicked Parts and Labor using {sel}")
                    break
            except:
                continue
        
        if not parts_labor_clicked:
            logger.warning("ALLDATA: Could not click Parts and Labor directly")
        
        # Step 6: Search for job description
        logger.info(f"ALLDATA: Searching for job: {job_description}")
        job_search_selectors = [
            "input[placeholder*='Search Parts']",
            "input[placeholder*='Search']",
            "#laborSearch",
            ".search-input"
        ]
        
        job_searched = False
        for sel in job_search_selectors:
            try:
                if await page.is_visible(sel):
                    await page.fill(sel, job_description)
                    await page.keyboard.press("Enter")
                    job_searched = True
                    logger.info(f"ALLDATA: Searched job using {sel}")
                    await asyncio.sleep(2)
                    break
            except:
                continue
        
        # Step 7: Click on first matching result
        if job_searched:
            try:
                # Try to click on first labor item in list
                result_selectors = [
                    f"text={job_description}",
                    ".labor-item",
                    "tr:has-text('Labor')",
                    "a:has-text('Labor')"
                ]
                for sel in result_selectors:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            await el.click()
                            await asyncio.sleep(2)
                            logger.info(f"ALLDATA: Clicked job result using {sel}")
                            break
                    except:
                        continue
            except:
                pass
        
        # Step 8: Extract labor hours from the page
        logger.info("ALLDATA: Extracting labor hours...")
        labor_hours = 0.0
        found_labor_hours = []
        
        labor_selectors = [
            "input[role='spinbutton']",
            "div.labor-column-quantity input",
            "input.p-inputnumber",
            ".labor-hours",
            "td.hours",
            "span:has-text('hrs')"
        ]
        
        for sel in labor_selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements[:10]:
                    # Try value attribute
                    try:
                        val = await el.get_attribute("value")
                        if val:
                            match = re.search(r'(\d+\.?\d*)', val)
                            if match:
                                hours = float(match.group(1))
                                if 0 < hours < 100:
                                    found_labor_hours.append(hours)
                                    logger.info(f"ALLDATA: Found labor: {hours} hrs")
                    except:
                        pass
                    # Try inner text
                    try:
                        text = await el.inner_text()
                        match = re.search(r'(\d+\.?\d*)', text)
                        if match:
                            hours = float(match.group(1))
                            if 0 < hours < 100:
                                found_labor_hours.append(hours)
                                logger.info(f"ALLDATA: Found labor: {hours} hrs")
                    except:
                        pass
                if found_labor_hours:
                    break
            except:
                continue
        
        # Return result
        if found_labor_hours:
            labor_hours = found_labor_hours[0]
            logger.info(f"ALLDATA: SUCCESS - Labor hours: {labor_hours}")
            return {
                "success": True,
                "labor_hours": labor_hours,
                "source": "alldata-live"
            }
        else:
            # DOM DISCOVERY - Auto-scan page for elements
            logger.error("ALLDATA: No labor hours found - running DOM Discovery...")
            discovered = await discover_page_elements(page, "price")
            return {
                "success": False,
                "error": f"Could not find labor hours for '{job_description}' in ALLDATA.",
                "discovered_elements": discovered.get("prices", [])[:5],
                "suggested_selectors": discovered.get("suggested_selectors", [])[:5]
            }
        
    except Exception as e:
        logger.error(f"ALLDATA scrape error: {e}")
        return {"success": False, "error": str(e)}

async def scrape_partslink_parts(vin: str, job_description: str) -> dict:
    """
    FULL AUTOMATION: Scrape OEM parts from PartsLink24
    Flow: Brand Menu → VIN Search → Vehicle Select → Navigate to Parts → Extract Part Numbers
    """
    logger.info(f"PARTSLINK: Full automation for VIN={vin}, Job={job_description}")
    
    browser, page, should_close = await get_existing_page_for_site("partslink")
    
    try:
        import re
        current_url = page.url.lower()
        
        # Step 1: Check if logged in
        if "partslink" not in current_url:
            await page.goto("https://www.partslink24.com/partslink24/user/brandMenu.do", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            current_url = page.url.lower()
        
        # Login detection - login.do means NOT logged in!
        is_logged_in = False
        if "partslink" in current_url:
            if "login.do" in current_url or "/login" in current_url:
                is_logged_in = False
                logger.warning("PARTSLINK: On login page - NOT logged in!")
            elif any(x in current_url for x in ["/brandmenu", "/p5.do", "/catalog", "/pl24-app"]):
                is_logged_in = True
        
        logger.info(f"PARTSLINK URL: {current_url}, Logged in: {is_logged_in}")
        
        if not is_logged_in:
            return {"success": False, "error": "Not logged into PartsLink24. Please login in Chrome first."}
        
        # Step 2: Navigate to brand menu if not there
        if "brandmenu" not in current_url and "pl24-app" not in current_url:
            await page.goto("https://www.partslink24.com/partslink24/user/brandMenu.do", wait_until="domcontentloaded")
            await asyncio.sleep(2)
        
        # Step 3: Enter VIN and search
        logger.info("PARTSLINK: Entering VIN...")
        vin_selectors = [
            "input[placeholder='Search VIN']",
            "input[placeholder*='VIN']",
            "input[name='text']",
            "#vinInput",
            "input.vin-search"
        ]
        
        vin_entered = False
        for sel in vin_selectors:
            try:
                if await page.is_visible(sel):
                    await page.fill(sel, "")  # Clear first
                    await page.fill(sel, vin)
                    logger.info(f"PARTSLINK: VIN entered using {sel}")
                    vin_entered = True
                    break
            except:
                continue
        
        if not vin_entered:
            return {"success": False, "error": "Could not find VIN search in PartsLink24"}
        
        # Step 4: Click search/GO button
        logger.info("PARTSLINK: Clicking search...")
        button_selectors = [
            ".search-btn",
            "div.search-btn",
            "button[type='submit']",
            "text=GO",
            "button:has-text('Search')"
        ]
        
        for btn_sel in button_selectors:
            try:
                el = await page.query_selector(btn_sel)
                if el:
                    await el.click()
                    logger.info(f"PARTSLINK: Clicked search using {btn_sel}")
                    break
            except:
                continue
        
        await asyncio.sleep(3)  # Wait for results
        
        # Step 5: If vehicle selection needed, try to click first option
        logger.info("PARTSLINK: Checking for vehicle selection...")
        try:
            # PartsLink sometimes shows model selection
            model_selectors = [
                "tr:first-child td a",
                ".model-row",
                "a.select-vehicle",
                "table tr:first-child"
            ]
            for sel in model_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.click()
                        await asyncio.sleep(2)
                        logger.info(f"PARTSLINK: Selected vehicle using {sel}")
                        break
                except:
                    continue
        except:
            pass
        
        # Step 6: Navigate to parts catalog/search
        logger.info(f"PARTSLINK: Searching for parts related to: {job_description}")
        search_selectors = [
            "input[placeholder*='Search']",
            "input[placeholder*='Part']",
            "#partSearch",
            ".catalog-search"
        ]
        
        for sel in search_selectors:
            try:
                if await page.is_visible(sel):
                    await page.fill(sel, job_description)
                    await page.keyboard.press("Enter")
                    logger.info(f"PARTSLINK: Searched using {sel}")
                    await asyncio.sleep(2)
                    break
            except:
                continue
        
        # Step 7: Extract part numbers from page
        logger.info("PARTSLINK: Extracting part numbers...")
        parts = []
        
        part_selectors = [
            ".oem-number",
            ".part-number",
            ".article-number",
            "td.part-num",
            "span.part-number",
            "[data-part-number]"
        ]
        
        for sel in part_selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements[:10]:
                    text = await el.inner_text()
                    text = text.strip()
                    if text and len(text) > 3:
                        # Clean up part number
                        part_num = re.sub(r'[^\w\d-]', '', text)
                        if part_num:
                            parts.append({
                                "part_number": part_num,
                                "description": f"{job_description} - OEM",
                                "manufacturer": "OEM",
                                "is_oem": True
                            })
                            logger.info(f"PARTSLINK: Found part: {part_num}")
                if parts:
                    break
            except:
                continue
        
        # Return result
        if parts:
            logger.info(f"PARTSLINK: SUCCESS - Found {len(parts)} parts")
            return {
                "success": True,
                "parts": parts,
                "source": "partslink-live"
            }
        else:
            # DOM DISCOVERY - Auto-scan page for elements
            logger.error("PARTSLINK: No parts found - running DOM Discovery...")
            discovered = await discover_page_elements(page, "all")
            return {
                "success": False,
                "parts": [],
                "error": f"Could not find OEM parts for '{job_description}' in PartsLink24.",
                "discovered_elements": discovered.get("inputs", [])[:5] + discovered.get("links", [])[:5],
                "suggested_selectors": discovered.get("suggested_selectors", [])[:5],
                "source": "partslink-error"
            }
        
    except Exception as e:
        logger.error(f"PARTSLINK scrape error: {e}")
        return {"success": False, "error": str(e)}


async def scrape_vendor_pricing(part_numbers: List[str]) -> dict:
    """
    FULL AUTOMATION: Scrape pricing from SSF
    Flow: Navigate to Catalog → Search Part Number → Extract Prices
    """
    logger.info(f"SSF: Full automation for part numbers: {part_numbers}")
    
    browser, page, should_close = await get_existing_page_for_site("ssf")
    prices = []
    
    try:
        import re
        current_url = page.url.lower()
        
        # Step 1: Navigate to SSF if not there
        if "ssf" not in current_url:
            await page.goto("https://shop.ssfautoparts.com/Catalog", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            current_url = page.url.lower()
        
        # Step 2: Check if logged in
        is_logged_in = "ssf" in current_url and not any(x in current_url for x in ["/login", "/signin", "/auth"])
        if any(x in current_url for x in ["/catalog", "/account", "/cart", "/checkout"]):
            is_logged_in = True
        
        logger.info(f"SSF URL: {current_url}, Logged in: {is_logged_in}")
        
        if not is_logged_in:
            return {"success": False, "error": "Not logged into SSF. Please login in Chrome first."}
        
        # Step 3: Navigate to catalog if not there
        if "/catalog" not in current_url:
            await page.goto("https://shop.ssfautoparts.com/Catalog", wait_until="domcontentloaded")
            await asyncio.sleep(2)
        
        # Step 4: Process each part number
        for part_num in part_numbers:
            # Skip placeholder part numbers
            if "MANUAL" in part_num.upper() or "LOOKUP" in part_num.upper():
                logger.warning(f"SSF: Skipping placeholder part number: {part_num}")
                continue
            
            try:
                logger.info(f"SSF: Searching for part: {part_num}")
                
                # Search for part
                search_selectors = [
                    "input.expressSearchInput",
                    "input[name='pCtrl.partNumForm']",
                    "input.form-control.expressSearchInput",
                    "input[placeholder*='Part']",
                    "#partSearch"
                ]
                
                part_entered = False
                for sel in search_selectors:
                    try:
                        if await page.is_visible(sel):
                            await page.fill(sel, "")  # Clear first
                            await page.fill(sel, part_num)
                            logger.info(f"SSF: Entered part using {sel}")
                            part_entered = True
                            break
                    except:
                        continue
                
                if not part_entered:
                    logger.warning(f"SSF: Could not enter part number {part_num}")
                    continue
                
                # Press Enter or click search
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)  # Wait for results
                
                # Extract prices
                price_selectors = [
                    ".personal-price-wrap span.ng-binding",
                    "span.ng-binding",
                    "input[id^='yourPrice']",
                    "td span",
                    ".pricing-wrap span",
                    ".price-value"
                ]
                
                found_prices = []
                for price_sel in price_selectors:
                    try:
                        elements = await page.query_selector_all(price_sel)
                        for el in elements[:10]:
                            text = await el.inner_text()
                            match = re.search(r'\$?([\d,]+\.?\d*)', text.replace(',', ''))
                            if match:
                                price_val = float(match.group(1))
                                if 0 < price_val < 10000:  # Reasonable range
                                    found_prices.append(price_val)
                                    logger.info(f"SSF: Found price ${price_val}")
                        if found_prices:
                            break
                    except:
                        continue
                
                # Use best price
                if found_prices:
                    price = min(found_prices)
                    logger.info(f"SSF: Best price for {part_num}: ${price}")
                    prices.append({
                        "vendor": "SSF",
                        "part_number": part_num,
                        "brand": "Aftermarket",
                        "price": price,
                        "stock_status": "In Stock",
                        "warehouse": "SSF Oakland"
                    })
                else:
                    logger.warning(f"SSF: No price found for {part_num}")
                    
            except Exception as e:
                logger.error(f"SSF error for {part_num}: {e}")
                continue
        
        # Return result
        if prices and any(p["price"] > 0 for p in prices):
            logger.info(f"SSF: SUCCESS - Found {len(prices)} prices")
            return {
                "success": True,
                "prices": prices,
                "source": "ssf-live"
            }
        else:
            # DOM DISCOVERY - Auto-scan page for elements
            logger.error("SSF: No prices found - running DOM Discovery...")
            discovered = await discover_page_elements(page, "price")
            return {
                "success": False,
                "prices": [],
                "error": "Could not find prices from SSF.",
                "discovered_elements": discovered.get("prices", [])[:5],
                "suggested_selectors": discovered.get("suggested_selectors", [])[:5],
                "source": "ssf-error"
            }
        
    except Exception as e:
        logger.error(f"SSF scrape error: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# API ENDPOINTS
# =============================================================================
@app.get("/")
async def root():
    return {
        "service": "Estimaro Scraper Service",
        "status": "running",
        "endpoints": ["/scrape/labor", "/scrape/parts", "/scrape/pricing", "/health"]
    }


@app.get("/health")
async def health_check():
    """Health check - also verifies Chrome CDP connection"""
    try:
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        await browser.close()
        return {"status": "healthy", "chrome_cdp": "connected"}
    except Exception as e:
        return {"status": "degraded", "chrome_cdp": "disconnected", "error": str(e)}


@app.post("/scrape/labor", response_model=LaborResponse)
async def scrape_labor(request: LaborRequest, api_key: str = Depends(verify_api_key)):
    """Scrape labor time from ALLDATA"""
    result = await scrape_alldata_labor(request.vin, request.job_description)
    
    return LaborResponse(
        success=result.get("success", False),
        labor_hours=result.get("labor_hours"),
        job_description=request.job_description,
        source=result.get("source", "alldata"),
        error=result.get("error")
    )


@app.post("/scrape/parts", response_model=PartsResponse)
async def scrape_parts(request: PartsRequest, api_key: str = Depends(verify_api_key)):
    """Scrape OEM parts from PartsLink24"""
    result = await scrape_partslink_parts(request.vin, request.job_description)
    
    parts = [PartItem(**p) for p in result.get("parts", [])]
    
    return PartsResponse(
        success=result.get("success", False),
        parts=parts,
        source=result.get("source", "partslink"),
        error=result.get("error")
    )


@app.post("/scrape/pricing", response_model=PricingResponse)
async def scrape_pricing(request: PricingRequest, api_key: str = Depends(verify_api_key)):
    """Scrape pricing from Worldpac/SSF"""
    result = await scrape_vendor_pricing(request.part_numbers)
    
    prices = [PriceItem(**p) for p in result.get("prices", [])]
    
    return PricingResponse(
        success=result.get("success", False),
        prices=prices,
        source=result.get("source", "vendor"),
        error=result.get("error")
    )


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Estimaro Scraper Service...")
    print(f"📡 Chrome CDP Port: {CDP_PORT}")
    print(f"🔑 API Key: {API_KEY[:10]}...")
    uvicorn.run(app, host="0.0.0.0", port=5000)
