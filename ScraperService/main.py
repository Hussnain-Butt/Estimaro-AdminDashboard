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


async def scrape_alldata_labor(vin: str, job_description: str) -> dict:
    """Scrape labor time from ALLDATA using existing logged-in tab"""
    logger.info(f"ALLDATA: Scraping labor for VIN={vin}, Job={job_description}")
    
    browser, page, should_close = await get_existing_page_for_site("alldata")
    
    try:
        # If this is an existing ALLDATA tab, we're already on the site
        current_url = page.url.lower()
        
        # If new page (not on alldata), navigate there
        if "alldata" not in current_url:
            await page.goto("https://my.alldata.com", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            current_url = page.url.lower()
        
        # URL-based login check: if we're on alldata but NOT on login page, we're logged in
        # Login pages typically have /login, /signin, /auth in URL
        is_logged_in = "alldata" in current_url and not any(x in current_url for x in ["/login", "/signin", "/auth", "authn"])
        
        # Also check if URL indicates we're in the app (migrate, home, dashboard)
        if any(x in current_url for x in ["/migrate", "/home", "/dashboard", "#/"]):
            is_logged_in = True
        
        logger.info(f"ALLDATA URL: {current_url}, Logged in: {is_logged_in}")
        
        if not is_logged_in:
            if should_close:
                await page.close()
            return {
                "success": False,
                "error": "Not logged into ALLDATA. Please login in Chrome first."
            }
        
        # Navigate to Select Vehicle page if not already there
        if "select-vehicle" not in current_url:
            await page.goto("https://my.alldata.com/migrate/repair/#/select-vehicle", wait_until="domcontentloaded")
            await asyncio.sleep(2)
        
        # VIN Search - Real selector from ALLDATA
        vin_selectors = ["#ymmeSearchBox", "input[placeholder*='VIN']", "input[placeholder*='Search']"]
        vin_entered = False
        for sel in vin_selectors:
            try:
                if await page.is_visible(sel):
                    await page.fill(sel, vin)
                    await page.keyboard.press("Enter")
                    vin_entered = True
                    logger.info(f"ALLDATA: Entered VIN using selector {sel}")
                    break
            except Exception as e:
                logger.warning(f"ALLDATA selector {sel} failed: {e}")
                continue
        
        if not vin_entered:
            logger.warning("ALLDATA: Could not find VIN input field")
        
        await asyncio.sleep(3)
        
        # After VIN search, need to navigate to Parts and Labor section
        # Check if we're on the vehicle info page and click Parts and Labor
        try:
            parts_labor_link = await page.query_selector("text=Parts and Labor")
            if parts_labor_link:
                await parts_labor_link.click()
                await asyncio.sleep(2)
                logger.info("ALLDATA: Clicked on Parts and Labor")
        except:
            logger.warning("ALLDATA: Could not find Parts and Labor link")
        
        # Try to find labor time from ALLDATA
        # Real selectors from ALLDATA Parts and Labor page
        import re
        labor_hours = 0.0
        
        # ALLDATA uses input[role="spinbutton"] for labor hours
        labor_selectors = [
            "input[role='spinbutton']",
            "div.labor-column-quantity input",
            "input.p-inputnumber",
            ".labor-column-quantity span",
            "td.hours-column"
        ]
        
        found_labor_hours = []
        for sel in labor_selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements[:5]:
                    # Try to get value attribute first (for inputs)
                    try:
                        val = await el.get_attribute("value")
                        if val:
                            match = re.search(r'(\d+\.?\d*)', val)
                            if match:
                                hours = float(match.group(1))
                                if hours > 0 and hours < 100:  # Reasonable range
                                    found_labor_hours.append(hours)
                                    logger.info(f"ALLDATA: Found labor hours: {hours}")
                    except:
                        # Try inner text
                        text = await el.inner_text()
                        match = re.search(r'(\d+\.?\d*)', text)
                        if match:
                            hours = float(match.group(1))
                            if hours > 0 and hours < 100:
                                found_labor_hours.append(hours)
                                logger.info(f"ALLDATA: Found labor hours: {hours}")
                if found_labor_hours:
                    break
            except:
                continue
        
        # Use the first/primary labor hour found
        if found_labor_hours:
            labor_hours = found_labor_hours[0]
            logger.info(f"ALLDATA: Using labor hours: {labor_hours}")
            
            if should_close:
                await page.close()
            
            return {
                "success": True,
                "labor_hours": labor_hours,
                "source": "alldata-live"
            }
        else:
            # NO FALLBACK - Return error
            logger.error("ALLDATA: No labor hours found - returning error")
            if should_close:
                await page.close()
            
            return {
                "success": False,
                "error": "Could not extract labor hours from ALLDATA. Please search manually."
            }
        
    except Exception as e:
        logger.error(f"ALLDATA scrape error: {e}")
        if should_close:
            try:
                await page.close()
            except:
                pass
        return {"success": False, "error": str(e)}


async def scrape_partslink_parts(vin: str, job_description: str) -> dict:
    """Scrape OEM parts from PartsLink24 using existing logged-in tab"""
    logger.info(f"PARTSLINK: Scraping parts for VIN={vin}, Job={job_description}")
    
    browser, page, should_close = await get_existing_page_for_site("partslink")
    
    try:
        # Get current URL
        current_url = page.url.lower()
        
        # If not on partslink, navigate there
        if "partslink" not in current_url:
            await page.goto("https://www.partslink24.com/partslink24/p5.do", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            current_url = page.url.lower()
        
        # URL-based login check: if on partslink and in user area, we're logged in
        is_logged_in = "partslink" in current_url and not any(x in current_url for x in ["/login", "/signin", "/auth"])
        
        # Check for logged-in indicators in URL
        if any(x in current_url for x in ["/user/", "/brandmenu", "/p5.do", "/catalog"]):
            is_logged_in = True
        
        logger.info(f"PARTSLINK URL: {current_url}, Logged in: {is_logged_in}")
        
        if not is_logged_in:
            if should_close:
                await page.close()
            return {
                "success": False,
                "error": "Not logged into PartsLink24. Please login in Chrome first."
            }
        
        # VIN Search - Real selectors from PartsLink24
        vin_selectors = [
            "input[placeholder='Search VIN']",
            "input[placeholder*='VIN']",
            "input[name='text']"
        ]
        vin_entered = False
        for sel in vin_selectors:
            try:
                if await page.is_visible(sel):
                    await page.fill(sel, vin)
                    logger.info(f"PARTSLINK: Entered VIN using selector {sel}")
                    vin_entered = True
                    break
            except Exception as e:
                logger.warning(f"PARTSLINK selector {sel} failed: {e}")
                continue
        
        # Click GO/Search button
        if vin_entered:
            try:
                # Try multiple button selectors
                button_selectors = [".search-btn", "div.search-btn", "button[type='submit']"]
                for btn_sel in button_selectors:
                    if await page.is_visible(btn_sel):
                        await page.click(btn_sel)
                        logger.info(f"PARTSLINK: Clicked search using {btn_sel}")
                        break
                await asyncio.sleep(3)
            except Exception as e:
                logger.warning(f"PARTSLINK: Search button click failed: {e}")
        
        # Try to get part numbers - NO FALLBACK
        parts = []
        oem_selectors = [".oem-number", ".part-number", ".article-number"]
        
        for sel in oem_selectors:
            try:
                elements = await page.query_selector_all(sel)
                for el in elements[:5]:  # Max 5 parts
                    text = await el.inner_text()
                    if text.strip():
                        parts.append({
                            "part_number": text.strip(),
                            "description": f"{job_description} - OEM",
                            "manufacturer": "OEM",
                            "is_oem": True
                        })
                if parts:
                    break
            except:
                continue
        
        if should_close:
            await page.close()
        
        # NO FALLBACK - Return error if no parts found
        if parts:
            return {
                "success": True,
                "parts": parts,
                "source": "partslink-live"
            }
        else:
            logger.error("PARTSLINK: No parts found - returning error")
            return {
                "success": False,
                "parts": [],
                "error": "Could not find OEM parts from PartsLink24. Please search manually.",
                "source": "partslink-error"
            }
        
    except Exception as e:
        logger.error(f"PARTSLINK scrape error: {e}")
        if should_close:
            try:
                await page.close()
            except:
                pass
        return {"success": False, "error": str(e)}


async def scrape_vendor_pricing(part_numbers: List[str]) -> dict:
    """Scrape pricing from SSF using existing logged-in tab"""
    logger.info(f"PRICING: Scraping prices for {part_numbers}")
    
    browser, page, should_close = await get_existing_page_for_site("ssf")
    prices = []
    
    try:
        # Get current URL
        current_url = page.url.lower()
        
        # If not on SSF, navigate there
        if "ssf" not in current_url:
            await page.goto("https://shop.ssfautoparts.com", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            current_url = page.url.lower()
        
        # URL-based login check: if on SSF and not on login page, we're logged in
        is_logged_in = "ssf" in current_url and not any(x in current_url for x in ["/login", "/signin", "/auth"])
        
        # Check for logged-in indicators in URL (catalog, account, etc.)
        if any(x in current_url for x in ["/catalog", "/account", "/cart", "/checkout"]):
            is_logged_in = True
        
        logger.info(f"SSF URL: {current_url}, Logged in: {is_logged_in}")
        
        if is_logged_in:
            for part_num in part_numbers:
                try:
                    # Search for part - Real selectors from SSF
                    search_selectors = [
                        "input.expressSearchInput",
                        "input[name='pCtrl.partNumForm']",
                        "input.form-control.expressSearchInput",
                        "input[placeholder*='Part']"
                    ]
                    
                    part_entered = False
                    for sel in search_selectors:
                        try:
                            if await page.is_visible(sel):
                                await page.fill(sel, part_num)
                                logger.info(f"SSF: Entered part number using selector {sel}")
                                part_entered = True
                                break
                        except:
                            continue
                    
                    if part_entered:
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(3)  # Wait for results
                    
                    # Try to get prices from SSF results table
                    # SSF shows multiple vendors/brands in a table format
                    import re
                    
                    # Get all price cells - SSF uses span.ng-binding for prices
                    # Located in .personal-price-wrap or pricing-wrap
                    price_selectors = [
                        ".personal-price-wrap span.ng-binding",
                        "span.ng-binding",
                        "input[id^='yourPrice']",
                        "td span",
                        ".pricing-wrap span"
                    ]
                    
                    found_prices = []
                    for price_sel in price_selectors:
                        try:
                            elements = await page.query_selector_all(price_sel)
                            for el in elements[:5]:  # Max 5 results
                                text = await el.inner_text()
                                # Look for dollar amounts
                                match = re.search(r'\$?([\d,]+\.?\d*)', text.replace(',', ''))
                                if match:
                                    price_val = float(match.group(1))
                                    if price_val > 0 and price_val < 10000:  # Reasonable price range
                                        found_prices.append(price_val)
                                        logger.info(f"SSF: Found price ${price_val}")
                            if found_prices:
                                break
                        except:
                            continue
                    
                    # Use lowest price found, or default
                    if found_prices:
                        price = min(found_prices)  # Best price
                        logger.info(f"SSF: Best price for {part_num}: ${price}")
                    else:
                        price = 0.0  # No price found
                        logger.warning(f"SSF: No price found for {part_num}")
                    
                    prices.append({
                        "vendor": "SSF",
                        "part_number": part_num,
                        "brand": "Aftermarket",
                        "price": price,
                        "stock_status": "In Stock" if price > 0 else "Check Stock",
                        "warehouse": "SSF Oakland"
                    })
                except Exception as e:
                    logger.error(f"SSF price extraction error: {e}")
                    continue
        
        if should_close:
            await page.close()
        
        # NO FALLBACK - Return error if no real prices found
        if prices and any(p["price"] > 0 for p in prices):
            return {
                "success": True,
                "prices": prices,
                "source": "ssf-live"
            }
        else:
            logger.error("SSF: No prices found - returning error")
            return {
                "success": False,
                "prices": [],
                "error": "Could not find prices from SSF. Please search manually.",
                "source": "ssf-error"
            }
        
    except Exception as e:
        logger.error(f"PRICING scrape error: {e}")
        if should_close:
            try:
                await page.close()
            except:
                pass
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
