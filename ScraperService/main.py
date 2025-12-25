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
from typing import Optional, List, Dict
from decimal import Decimal

# Import Worldpac desktop automation (optional - may not be available on all systems)
try:
    from worldpac_desktop import worldpac_automation, WorldpacAutomation
    WORLDPAC_AVAILABLE = True
except ImportError:
    WORLDPAC_AVAILABLE = False
    worldpac_automation = None

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
    vin: Optional[str] = None  # Optional: for Worldpac VIN search
    job_description: Optional[str] = None  # Optional: for Worldpac job search


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
            "a.itype-name:has-text('Parts and Labor')",  # Link in description list
            "text=Parts and Labor >> nth=0",  # First matching text
            "a:has-text('Parts and Labor')",
            ".description-system a:has-text('Parts')",
            ".ad-repair-itype-table a:has-text('Parts')"
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
        
        # Step 6: Search for job description (ONLY if we're on Parts and Labor page)
        # IMPORTANT: Do NOT use selectors that match VIN search box!
        logger.info(f"ALLDATA: Searching for job: {job_description}")
        job_search_selectors = [
            "#txtTypeSearch",  # Real selector from DevTools
            "input[placeholder='Search Parts and Labor']",  # Exact placeholder
            "input.form-control[type='search']",
            ".itype-search-input input",
            "ad-uib-searchbox input"
            # NOTE: Do NOT add generic "input[placeholder*='Search']" - it matches VIN field!
        ]
        
        job_searched = False
        for sel in job_search_selectors:
            try:
                if await page.is_visible(sel):
                    # Make sure this is NOT the VIN field
                    el = await page.query_selector(sel)
                    if el:
                        el_id = await el.get_attribute("id")
                        if el_id == "ymmeSearchBox":
                            continue  # Skip VIN field!
                    await page.fill(sel, job_description)
                    await page.keyboard.press("Enter")
                    job_searched = True
                    logger.info(f"ALLDATA: Searched job using {sel}")
                    await asyncio.sleep(2)
                    break
            except:
                continue
        
        # Step 7: Click on MATCHING result - prioritize job-specific selectors
        if job_searched:
            try:
                # IMPORTANT: Try job-specific selectors FIRST, then generic ones
                result_selectors = [
                    f"a:has-text('{job_description}')",  # Exact text match FIRST!
                    f"text={job_description} >> nth=0",   # First matching text
                    f"a:has-text('{job_description.split()[0]}')",  # First word match
                    "a.itype-name >> nth=0",  # First link in list (fallback)
                    ".ad-repair-itype-table a >> nth=0",  # First table link (fallback)
                ]
                
                clicked = False
                for sel in result_selectors:
                    try:
                        # Wait briefly for results to appear
                        await asyncio.sleep(0.5)
                        el = await page.query_selector(sel)
                        if el:
                            # Verify the element text contains our job keyword
                            text = await el.text_content()
                            if text and (job_description.lower() in text.lower() or 
                                        job_description.split()[0].lower() in text.lower()):
                                await el.click()
                                await asyncio.sleep(2)
                                logger.info(f"ALLDATA: Clicked job result using {sel}, text: {text[:50]}")
                                clicked = True
                                break
                            elif "itype-name" in sel or "itype-table" in sel:
                                # Fallback - click anyway but log warning
                                await el.click()
                                await asyncio.sleep(2)
                                logger.warning(f"ALLDATA: Clicked FALLBACK result using {sel}, text: {text[:50] if text else 'N/A'}")
                                clicked = True
                                break
                    except Exception as e:
                        logger.debug(f"ALLDATA: Selector {sel} failed: {e}")
                        continue
                
                if not clicked:
                    logger.warning("ALLDATA: Could not click any job result")
            except Exception as e:
                logger.warning(f"ALLDATA: Error clicking job result: {e}")
        
        # Step 8: Extract labor hours from the page
        logger.info("ALLDATA: Extracting labor hours...")
        labor_hours = 0.0
        found_labor_hours = []
        
        labor_selectors = [
            "div.labor-column-standard",  # Main selector from DevTools - shows STANDARD hours
            "div.labor-columns div.labor-column-standard",  # More specific
            ".labor-column-quantity",  # Quantity column
            "div.labor-column-warranty",  # WARRANTY column has hours too
            "input[role='spinbutton']",  # Input boxes for hours
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
            elif any(x in current_url for x in ["/brandmenu", "/p5.do", "/catalog", "/pl24-app", "startup.do"]):
                is_logged_in = True
        
        logger.info(f"PARTSLINK URL: {current_url}, Logged in: {is_logged_in}")
        
        if not is_logged_in:
            return {"success": False, "error": "Not logged into PartsLink24. Please login in Chrome first."}
        
        # Step 2: ALWAYS navigate to startup.do for fresh VIN search
        # This fixes issue where tab is already on search results and VIN input is missing
        if "startup.do" not in current_url:
            logger.info("PARTSLINK: Navigating to startup.do for fresh search...")
            await page.goto("https://www.partslink24.com/partslink24/startup.do", wait_until="domcontentloaded")
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
            "#tooltip-go",  # Real selector from DevTools
            "div.search-btn",
            ".search-btn",
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
        
        # Step 5: If vehicle selection page, click "To the parts catalog"
        logger.info("PARTSLINK: Checking for 'To the parts catalog' button...")
        catalog_clicked = False
        try:
            catalog_selectors = [
                "text=To the parts catalog",  # Exact text
                "button:has-text('parts catalog')",
                "text=To the parts",  # Partial match
                "div:has-text('To the parts catalog')",
                "text=Select new vehicle",  # Alternative - go back and try again
            ]
            for sel in catalog_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        is_visible = await el.is_visible()
                        logger.info(f"PARTSLINK: Found '{sel}', visible={is_visible}")
                        if is_visible:
                            await el.click()
                            await asyncio.sleep(3)
                            logger.info(f"PARTSLINK: Clicked catalog using {sel}")
                            catalog_clicked = True
                            break
                except Exception as e:
                    logger.debug(f"PARTSLINK: Selector {sel} failed: {e}")
                    continue
        except Exception as e:
            logger.warning(f"PARTSLINK: Catalog button search failed: {e}")
        
        # Step 6: FIRST try to search for parts using job description
        # This ensures we find parts related to the actual problem (Air Conditioner, not Radiator)
        logger.info(f"PARTSLINK: Searching for parts related to: {job_description}")
        
        # Wait for page to fully load
        await asyncio.sleep(2)
        
        # Step 6a: Use "Search for parts" input with job description
        search_selectors = [
            "input[placeholder='Search for parts']",  # Exact match - safest
        ]
        
        searched = False
        for sel in search_selectors:
            try:
                try:
                    await page.wait_for_selector(sel, timeout=3000)
                except:
                    continue
                    
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    logger.info(f"PARTSLINK: Search input found with {sel}")
                    await el.fill(job_description)  # Search for "Air Conditioner"
                    await page.keyboard.press("Enter")
                    logger.info(f"PARTSLINK: Searched for '{job_description}' using {sel}")
                    await asyncio.sleep(3)
                    searched = True
                    break
            except Exception as e:
                logger.debug(f"PARTSLINK: Search selector '{sel}' error: {e}")
                continue
        
        # Step 6b: If search didn't work, try clicking relevant main group
        # Build dynamic selectors based on job description keywords
        main_group_clicked = False
        if not searched:
            logger.info("PARTSLINK: Search failed, trying main group click...")
            
            # Build selectors based on job description keywords
            job_lower = job_description.lower()
            main_group_keywords = []
            
            # Map job descriptions to relevant main groups
            if "air" in job_lower or "condition" in job_lower or "ac" in job_lower or "hvac" in job_lower:
                main_group_keywords = ["Air", "Climate", "Heating", "Ventilation", "64"]
            elif "engine" in job_lower or "motor" in job_lower:
                main_group_keywords = ["Engine", "Motor", "11"]
            elif "brake" in job_lower:
                main_group_keywords = ["Brake", "34"]
            elif "oil" in job_lower:
                main_group_keywords = ["Engine", "Oil", "11"]
            elif "radiator" in job_lower or "cooling" in job_lower:
                main_group_keywords = ["Radiator", "Cooling", "17"]
            else:
                # Default: try to match job description directly
                main_group_keywords = [job_description, "Parts Repair"]
            
            # Build selectors from keywords
            main_group_selectors = []
            for keyword in main_group_keywords:
                main_group_selectors.append(f"div[data-test-id='row']:has-text('{keyword}')")
                main_group_selectors.append(f"span:has-text('{keyword}')")
            
            for sel in main_group_selectors:
                try:
                    try:
                        await page.wait_for_selector(sel, timeout=2000)
                    except:
                        continue
                        
                    el = await page.query_selector(sel)
                    if el:
                        is_visible = await el.is_visible()
                        logger.info(f"PARTSLINK: Main group '{sel}' found, visible={is_visible}")
                        if is_visible:
                            try:
                                await el.click()
                                logger.info(f"PARTSLINK: Clicked main group using {sel}")
                            except Exception as click_err:
                                logger.error(f"PARTSLINK: Click FAILED: {click_err}")
                                continue
                            await asyncio.sleep(3)
                            main_group_clicked = True
                            break
                except Exception as e:
                    continue
        
        if not searched and not main_group_clicked:
            logger.warning("PARTSLINK: Could not search or click main group")
        
        # Step 8: Extract part numbers from page
        # Part numbers are in format XX_XXXX (e.g., 17_0525, 17_0464)
        logger.info("PARTSLINK: Extracting part numbers...")
        parts = []
        
        # First try to find all text on page matching part number pattern
        try:
            page_content = await page.content()
            # Pattern: 2 digits, underscore, 4 digits (e.g., 17_0525)
            part_pattern = r'\b(\d{2}_\d{4})\b'
            found_parts = re.findall(part_pattern, page_content)
            unique_parts = list(set(found_parts))[:10]  # Limit to 10 unique parts
            
            for part_num in unique_parts:
                parts.append({
                    "part_number": part_num,
                    "description": f"{job_description} - OEM",
                    "manufacturer": "BMW OEM",  # Since it's PartsLink for BMW
                    "is_oem": True
                })
                logger.info(f"PARTSLINK: Found part: {part_num}")
        except Exception as e:
            logger.warning(f"PARTSLINK: Regex extraction failed: {e}")
        
        # If regex didn't find parts, try DOM selectors
        if not parts:
            part_selectors = [
                "td:has-text('_')",  # Cells with underscore (part numbers)
                "span:has-text('_')",
                ".description",
            ]
            
            for sel in part_selectors:
                try:
                    elements = await page.query_selector_all(sel)
                    for el in elements[:15]:
                        text = await el.inner_text()
                        # Find part numbers in text
                        matches = re.findall(r'\b(\d{2}_\d{4})\b', text)
                        for part_num in matches:
                            if part_num not in [p["part_number"] for p in parts]:
                                parts.append({
                                    "part_number": part_num,
                                    "description": f"{job_description} - OEM",
                                    "manufacturer": "BMW OEM",
                                    "is_oem": True
                                })
                                logger.info(f"PARTSLINK: Found part via DOM: {part_num}")
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
# WORLDPAC DESKTOP AUTOMATION
# =============================================================================
async def scrape_worldpac_pricing(part_numbers: List[str], vin: str = None, job_description: str = None) -> dict:
    """
    Scrape pricing from Worldpac speedDIAL desktop application.
    Uses pyautogui/pywinauto for Windows GUI automation.
    
    If VIN and job_description are provided, uses complete search flow.
    """
    if not WORLDPAC_AVAILABLE:
        logger.warning("WORLDPAC: Desktop automation not available - pyautogui/pywinauto not installed")
        return {"success": False, "error": "Worldpac desktop automation not available", "prices": []}
    
    try:
        logger.info(f"WORLDPAC: Requesting prices for {len(part_numbers)} parts")
        if vin:
            logger.info(f"WORLDPAC: Using VIN: {vin}")
        if job_description:
            logger.info(f"WORLDPAC: Using Job: {job_description}")
        
        # Get prices from Worldpac desktop app
        results = await worldpac_automation.get_prices(part_numbers, vin=vin, job_description=job_description)
        
        if results:
            prices = []
            for r in results:
                prices.append({
                    "vendor": "Worldpac",
                    "part_number": r.get("part_number", ""),
                    "brand": "OEM",
                    "price": float(r.get("price", 0)),
                    "stock_status": r.get("stock_status", "Available"),
                    "warehouse": "Worldpac"
                })
            
            logger.info(f"WORLDPAC: SUCCESS - Found {len(prices)} prices")
            return {
                "success": True,
                "prices": prices,
                "source": "worldpac-desktop"
            }
        else:
            logger.warning("WORLDPAC: No prices found (search flow completed)")
            return {"success": False, "error": "Worldpac search completed - check screenshots", "prices": []}
            
    except Exception as e:
        logger.error(f"WORLDPAC: Error - {e}")
        return {"success": False, "error": str(e), "prices": []}


# =============================================================================
# MULTI-VENDOR PRICE COMPARISON
# =============================================================================
async def scrape_multi_vendor_pricing(part_numbers: List[str], vin: str = None, job_description: str = None) -> dict:
    """
    Search BOTH SSF and Worldpac for prices, then compare and pick cheapest.
    
    Flow:
    1. Search SSF (web) for all parts
    2. Search Worldpac (desktop) for parts not found on SSF or for comparison
    3. Compare prices and pick cheapest vendor for each part
    4. Return merged results with vendor comparison
    """
    logger.info(f"MULTI-VENDOR: Starting price comparison for {len(part_numbers)} parts")
    
    all_prices = []
    ssf_prices = {}
    worldpac_prices = {}
    
    # Step 1: Get SSF prices
    try:
        ssf_result = await scrape_vendor_pricing(part_numbers)
        if ssf_result.get("success"):
            for p in ssf_result.get("prices", []):
                part_num = p.get("part_number")
                if part_num:
                    ssf_prices[part_num] = p
            logger.info(f"MULTI-VENDOR: SSF returned {len(ssf_prices)} prices")
    except Exception as e:
        logger.warning(f"MULTI-VENDOR: SSF search failed - {e}")
    
    # Step 2: Get Worldpac prices (for parts not found on SSF, or for comparison)
    parts_for_worldpac = []
    for part_num in part_numbers:
        # Search Worldpac if:
        # - Part not found on SSF, OR
        # - We want to compare prices
        if part_num not in ssf_prices or True:  # Always search for comparison
            parts_for_worldpac.append(part_num)
    
    if parts_for_worldpac and WORLDPAC_AVAILABLE:
        try:
            # Pass VIN and job description for complete Worldpac search flow
            worldpac_result = await scrape_worldpac_pricing(parts_for_worldpac, vin=vin, job_description=job_description)
            if worldpac_result.get("success"):
                for p in worldpac_result.get("prices", []):
                    part_num = p.get("part_number")
                    if part_num:
                        worldpac_prices[part_num] = p
                logger.info(f"MULTI-VENDOR: Worldpac returned {len(worldpac_prices)} prices")
        except Exception as e:
            logger.warning(f"MULTI-VENDOR: Worldpac search failed - {e}")
    
    # Step 3: Compare and pick cheapest
    comparison_results = []
    for part_num in part_numbers:
        ssf_price = ssf_prices.get(part_num)
        worldpac_price = worldpac_prices.get(part_num)
        
        if ssf_price and worldpac_price:
            # Both vendors have price - pick cheapest
            ssf_val = float(ssf_price.get("price", 9999))
            wp_val = float(worldpac_price.get("price", 9999))
            
            if ssf_val <= wp_val:
                primary = ssf_price
                secondary = worldpac_price
            else:
                primary = worldpac_price
                secondary = ssf_price
            
            comparison_results.append({
                "part_number": part_num,
                "primary": primary,
                "secondary": secondary,
                "savings": abs(ssf_val - wp_val),
                "cheaper_vendor": primary.get("vendor")
            })
            all_prices.append(primary)
            
        elif ssf_price:
            # Only SSF has price
            comparison_results.append({
                "part_number": part_num,
                "primary": ssf_price,
                "secondary": None,
                "savings": 0,
                "cheaper_vendor": "SSF"
            })
            all_prices.append(ssf_price)
            
        elif worldpac_price:
            # Only Worldpac has price
            comparison_results.append({
                "part_number": part_num,
                "primary": worldpac_price,
                "secondary": None,
                "savings": 0,
                "cheaper_vendor": "Worldpac"
            })
            all_prices.append(worldpac_price)
        
        else:
            # Neither vendor has price
            logger.warning(f"MULTI-VENDOR: No price from any vendor for {part_num}")
    
    logger.info(f"MULTI-VENDOR: Final result - {len(all_prices)} prices from {len(comparison_results)} comparisons")
    
    return {
        "success": len(all_prices) > 0,
        "prices": all_prices,
        "comparison": comparison_results,
        "vendors_searched": ["SSF"] + (["Worldpac"] if WORLDPAC_AVAILABLE else []),
        "source": "multi-vendor"
    }


# =============================================================================
# API ENDPOINTS
# =============================================================================
@app.get("/")
async def root():
    return {
        "service": "Estimaro Scraper Service",
        "status": "running",
        "endpoints": [
            "/scrape/labor", 
            "/scrape/parts", 
            "/scrape/pricing",
            "/scrape/worldpac",
            "/scrape/multi-vendor",
            "/health"
        ],
        "worldpac_available": WORLDPAC_AVAILABLE
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


@app.post("/scrape/worldpac", response_model=PricingResponse)
async def scrape_worldpac(request: PricingRequest, api_key: str = Depends(verify_api_key)):
    """Scrape pricing from Worldpac speedDIAL desktop app"""
    result = await scrape_worldpac_pricing(
        request.part_numbers, 
        vin=request.vin, 
        job_description=request.job_description
    )
    
    prices = [PriceItem(**p) for p in result.get("prices", [])]
    
    return PricingResponse(
        success=result.get("success", False),
        prices=prices,
        source=result.get("source", "worldpac"),
        error=result.get("error")
    )


@app.post("/scrape/multi-vendor")
async def scrape_all_vendors(request: PricingRequest, api_key: str = Depends(verify_api_key)):
    """
    Search BOTH SSF and Worldpac for prices.
    Compares prices and picks the cheapest vendor for each part.
    Returns comparison data with savings information.
    """
    result = await scrape_multi_vendor_pricing(
        request.part_numbers,
        vin=request.vin,
        job_description=request.job_description
    )
    return result


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Estimaro Scraper Service...")
    print(f"📡 Chrome CDP Port: {CDP_PORT}")
    print(f"🔑 API Key: {API_KEY[:10]}...")
    uvicorn.run(app, host="0.0.0.0", port=5000)
