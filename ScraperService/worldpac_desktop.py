"""
Worldpac speedDIAL Desktop Automation
=====================================
Automates the Worldpac speedDIAL desktop application using pyautogui, pywinauto, and OCR.
Now with AI-powered element detection and self-healing capabilities!

Requirements:
    pip install pyautogui pywinauto pillow pytesseract google-generativeai

Usage:
    from worldpac_desktop import WorldpacAutomation
    wp = WorldpacAutomation(ai_enabled=True)
    prices = wp.get_prices_for_vin("WBA3B1C59FK456789", "Brake")
"""

import logging
import time
import re
import os
import asyncio
from typing import List, Dict, Optional
from decimal import Decimal

# Try to import automation libraries
try:
    import pyautogui
    from pywinauto import Application
    AUTOMATION_AVAILABLE = True
except ImportError:
    AUTOMATION_AVAILABLE = False
    pyautogui = None

# Try to import OCR
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    pytesseract = None

# Try to import Gemini AI Agent
try:
    from gemini_agent import GeminiVisionAgent
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    GeminiVisionAgent = None

# Try to import nest_asyncio for running async in sync context
try:
    import nest_asyncio
    nest_asyncio.apply()
    NEST_ASYNCIO_AVAILABLE = True
except ImportError:
    NEST_ASYNCIO_AVAILABLE = False

logger = logging.getLogger(__name__)


def run_async_safe(coro):
    """Run an async coroutine safely from sync code, handling nested event loops."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context (like FastAPI)
            # Use nest_asyncio or create new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        # No event loop, create new one
        return asyncio.run(coro)


# =============================================================================
# CONFIGURATION - Coordinates captured from user's screen
# =============================================================================
CONFIG = {
    # VIN field (relative to catalog window)
    "vin_field_rel": (467, 73),
    "vin_search_rel": (528, 71),
    
    # Category search (relative to catalog)
    "category_search_rel": (150, 180),
    "search_result_rel": (150, 230),
    
    # Checkbox in right panel (relative to catalog)
    "parts_checkbox_rel": (880, 273),
    
    # Price button (relative to catalog)
    "price_button_rel": (1098, 641),
    
    # Vehicle selection popup (absolute)
    "vehicle_row_abs": (632, 276),
}


class WorldpacAutomation:
    """Automates Worldpac speedDIAL desktop application with AI assistance."""
    
    def __init__(self, ai_enabled: bool = True, gemini_api_key: str = None):
        self.app = None
        self.catalog = None
        self.win_left = 0
        self.win_top = 0
        self.connected = False
        
        # AI Agent for intelligent automation
        self.ai_agent = None
        self.ai_enabled = ai_enabled
        
        if ai_enabled and AI_AVAILABLE:
            api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
            if api_key:
                self.ai_agent = GeminiVisionAgent(api_key)
                logger.info("✅ AI Agent enabled for Worldpac automation")
            else:
                logger.warning("GEMINI_API_KEY not set - AI features disabled")
        
        if not AUTOMATION_AVAILABLE:
            logger.warning("Desktop automation not available - missing pyautogui/pywinauto")
        if not OCR_AVAILABLE:
            logger.warning("OCR not available - missing pytesseract")
    
    def _log(self, message: str, level: str = "info"):
        """Log message."""
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)
        print(f"[Worldpac] {message}")
    
    def connect(self) -> bool:
        """Connect to Worldpac speedDIAL application."""
        if not AUTOMATION_AVAILABLE:
            self._log("Automation libraries not available", "error")
            return False
            
        try:
            self._log("Connecting to Worldpac speedDIAL...")
            
            self.app = Application(backend="uia").connect(
                title_re=".*WORLDPAC speedDIAL.*",
                timeout=10
            )
            
            # Find main window
            main_win = self.app.window(title_re=".*WORLDPAC speedDIAL.*")
            
            # Find Catalog child window
            self.catalog = None
            for child in main_win.children(control_type="Window"):
                title = child.window_text()
                if "Catalog" in title:
                    self.catalog = child
                    break
            
            if not self.catalog:
                try:
                    self.catalog = self.app.window(title_re=".*Catalog.*")
                except:
                    self.catalog = main_win
            
            # Get window position
            rect = self.catalog.rectangle()
            self.win_left = rect.left
            self.win_top = rect.top
            
            # Focus window
            self.catalog.set_focus()
            time.sleep(0.5)
            
            self.connected = True
            self._log(f"Connected! Window at ({self.win_left}, {self.win_top})")
            return True
            
        except Exception as e:
            self._log(f"Connection failed: {e}", "error")
            return False
    
    def _click_relative(self, coord_name: str):
        """Click at relative position."""
        x = self.win_left + CONFIG[coord_name][0]
        y = self.win_top + CONFIG[coord_name][1]
        pyautogui.click(x, y)
        time.sleep(0.3)
    
    def _click_absolute(self, x: int, y: int):
        """Click at absolute position."""
        pyautogui.click(x, y)
        time.sleep(0.3)
    
    def _update_window_position(self):
        """Update window position (may have moved)."""
        try:
            rect = self.catalog.rectangle()
            self.win_left = rect.left
            self.win_top = rect.top
        except:
            pass
    
    # =========================================================================
    # AI-POWERED AUTOMATION METHODS
    # =========================================================================
    
    def _find_element_with_ai(self, description: str) -> Optional[tuple]:
        """
        Use AI Vision to find element coordinates dynamically.
        
        Args:
            description: What to find (e.g., "VIN input field", "Price button")
            
        Returns:
            (x, y) coordinates or None if not found/AI disabled
        """
        if not self.ai_agent or not self.ai_agent.initialized:
            return None
        
        try:
            self._log(f"[AI] Finding: {description}")
            
            # Take screenshot
            screenshot = pyautogui.screenshot()
            
            # Ask AI to find the element
            result = run_async_safe(self.ai_agent.find_element(screenshot, description))
            
            if result.get("success"):
                x, y = result["x"], result["y"]
                confidence = result.get("confidence", 0)
                self._log(f"[AI] Found at ({x}, {y}) confidence={confidence:.2f}")
                return (x, y)
            else:
                self._log(f"[AI] Not found: {result.get('error', 'Unknown')}", "warning")
                return None
                
        except Exception as e:
            self._log(f"[AI] Error: {e}", "error")
            return None
    
    def _click_with_ai_fallback(self, coord_name: str, ai_description: str) -> bool:
        """
        Click using hardcoded coords, with AI fallback if first click fails.
        
        Args:
            coord_name: Config key for hardcoded coordinates
            ai_description: Description for AI to find element if needed
            
        Returns:
            True if click likely succeeded
        """
        try:
            # Try hardcoded coords first (faster)
            x = self.win_left + CONFIG[coord_name][0]
            y = self.win_top + CONFIG[coord_name][1]
            pyautogui.click(x, y)
            time.sleep(0.3)
            return True
        except Exception as e:
            self._log(f"Hardcoded click failed: {e}", "warning")
            
            # Fallback to AI
            coords = self._find_element_with_ai(ai_description)
            if coords:
                pyautogui.click(coords[0], coords[1])
                time.sleep(0.3)
                return True
            
            return False
    
    def _click_with_healing(self, description: str, fallback_coords: tuple = None, max_retries: int = 2) -> bool:
        """
        Click element with AI-powered self-healing retry.
        
        Args:
            description: What to click (for AI)
            fallback_coords: (x, y) to try if AI fails
            max_retries: Maximum retry attempts
            
        Returns:
            True if click succeeded
        """
        for attempt in range(max_retries + 1):
            try:
                # Try AI first if available
                if self.ai_agent and attempt > 0:
                    # Take screenshot and ask AI where to click
                    screenshot = pyautogui.screenshot()
                    result = run_async_safe(self.ai_agent.analyze_failure(
                        screenshot,
                        f"Need to click: {description}",
                        f"Attempt {attempt + 1}/{max_retries + 1}"
                    ))
                    
                    if result.get("new_coords"):
                        x, y = result["new_coords"]["x"], result["new_coords"]["y"]
                        self._log(f"[AI] Retry with new coords ({x}, {y}): {result.get('diagnosis', '')}")
                        pyautogui.click(x, y)
                        time.sleep(0.5)
                        return True
                
                # Use fallback coords
                if fallback_coords:
                    pyautogui.click(fallback_coords[0], fallback_coords[1])
                    time.sleep(0.3)
                    return True
                    
            except Exception as e:
                self._log(f"Click attempt {attempt + 1} failed: {e}", "warning")
                continue
        
        return False
    
    async def get_smart_keywords(self, job_description: str) -> List[str]:
        """
        Get AI-expanded keywords for a job description.
        
        Args:
            job_description: Original job description
            
        Returns:
            List of keywords to try when searching
        """
        if not self.ai_agent:
            # Fallback: return first word
            return [job_description.split()[0]] if job_description else []
        
        return await self.ai_agent.get_search_keywords(job_description)

    
    def _enter_vin(self, vin: str) -> bool:
        """Enter VIN and search."""
        try:
            self._log(f"Entering VIN: {vin}")
            
            # Click VIN field
            self._click_relative("vin_field_rel")
            
            # Clear and type VIN
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('delete')
            time.sleep(0.1)
            
            pyautogui.typewrite(vin, interval=0.05)
            time.sleep(0.5)
            
            # Click search
            self._click_relative("vin_search_rel")
            time.sleep(4)  # Wait for VIN lookup
            
            self._log("VIN entered and searched")
            return True
            
        except Exception as e:
            self._log(f"VIN entry failed: {e}", "error")
            return False
    
    def _select_vehicle(self) -> bool:
        """Select vehicle from popup or auto-selected."""
        try:
            self._log("Selecting vehicle...")
            
            # Double-click on vehicle row
            x, y = CONFIG["vehicle_row_abs"]
            pyautogui.doubleClick(x, y)
            time.sleep(2)
            
            self._log("Vehicle selection attempted")
            return True
            
        except Exception as e:
            self._log(f"Vehicle selection failed: {e}", "error")
            return False
    
    def _search_job(self, job: str) -> bool:
        """Search for job description in category field."""
        try:
            # Simplify job to first word for better search results
            # e.g., "Oil Change Service" -> "Oil"
            # e.g., "Brake Pad Replacement" -> "Brake"
            search_term = job.split()[0] if job else job
            
            self._log(f"Searching for job: {search_term} (from '{job}')")
            self._update_window_position()
            
            # Click category search
            search_x = self.win_left + CONFIG["category_search_rel"][0]
            search_y = self.win_top + CONFIG["category_search_rel"][1]
            pyautogui.click(search_x, search_y)
            time.sleep(0.3)
            
            # Clear and type job
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('delete')
            time.sleep(0.1)
            
            pyautogui.typewrite(search_term, interval=0.03)
            pyautogui.press('enter')
            time.sleep(2)
            
            self._log(f"Job '{search_term}' searched")
            return True
            
        except Exception as e:
            self._log(f"Job search failed: {e}", "error")
            return False
    
    def _click_search_result(self) -> bool:
        """Click on first search result."""
        try:
            self._log("Clicking search result...")
            
            result_x = self.win_left + CONFIG["search_result_rel"][0]
            result_y = self.win_top + CONFIG["search_result_rel"][1]
            pyautogui.click(result_x, result_y)
            time.sleep(2)
            
            self._log("Search result clicked")
            return True
            
        except Exception as e:
            self._log(f"Result click failed: {e}", "error")
            return False
    
    def _select_all_parts(self) -> int:
        """Select all parts in right panel."""
        try:
            self._log("Selecting all parts...")
            
            checkbox_x = self.win_left + CONFIG["parts_checkbox_rel"][0]
            start_y = self.win_top + 210
            row_spacing = 25
            max_rows = 15
            
            parts_selected = 0
            
            # Click all visible checkboxes
            for i in range(max_rows):
                checkbox_y = start_y + (i * row_spacing)
                if checkbox_y > self.win_top + 550:
                    break
                pyautogui.click(checkbox_x, checkbox_y)
                time.sleep(0.1)
                parts_selected += 1
            
            # Scroll and click more
            pyautogui.scroll(-5)
            time.sleep(0.5)
            
            for i in range(5):
                checkbox_y = start_y + (i * row_spacing)
                pyautogui.click(checkbox_x, checkbox_y)
                time.sleep(0.1)
                parts_selected += 1
            
            self._log(f"Selected ~{parts_selected} parts")
            return parts_selected
            
        except Exception as e:
            self._log(f"Part selection failed: {e}", "error")
            return 0
    
    def _click_price_button(self) -> bool:
        """Click the Price button with retry logic."""
        try:
            self._log("Clicking Price button...")
            
            # Update window position first
            self._update_window_position()
            
            # Try clicking multiple times with different wait times
            for attempt in range(3):
                price_x = self.win_left + CONFIG["price_button_rel"][0]
                price_y = self.win_top + CONFIG["price_button_rel"][1]
                
                # Double-click on first attempt
                if attempt == 0:
                    pyautogui.click(price_x, price_y)
                    time.sleep(0.5)
                    pyautogui.click(price_x, price_y)  # Double click
                else:
                    # Slightly different coordinates on retry
                    pyautogui.click(price_x - 20 + (attempt * 10), price_y)
                
                self._log(f"Price button click attempt {attempt + 1}")
                time.sleep(5)  # Increased wait time for price popup to load
                
                # Take a quick screenshot to check if popup appeared
                # (AI will analyze later if needed)
                break
            
            self._log("Price button clicked - waiting for prices to load...")
            time.sleep(3)  # Extra wait for price data to load
            return True
            
        except Exception as e:
            self._log(f"Price button click failed: {e}", "error")
            return False
    
    def _extract_prices_ocr(self) -> List[float]:
        """Extract all prices using OCR with scrolling, with AI fallback."""
        if not OCR_AVAILABLE:
            self._log("OCR not available", "warning")
            return []
        
        try:
            self._log("Extracting prices via OCR...")
            time.sleep(2)
            
            all_prices = []
            scroll_count = 0
            max_scrolls = 5
            
            while scroll_count < max_scrolls:
                # Take screenshot
                screenshot = pyautogui.screenshot()
                
                # OCR extraction
                text = pytesseract.image_to_string(screenshot)
                
                # Find price patterns
                price_pattern = r'\$(\d+\.?\d{0,2})'
                matches = re.findall(price_pattern, text)
                
                new_prices = 0
                for m in matches:
                    try:
                        price = float(m)
                        if 1.0 <= price <= 5000:  # Increased range
                            if price not in all_prices:
                                all_prices.append(price)
                                new_prices += 1
                    except:
                        pass
                
                self._log(f"  Page {scroll_count + 1}: {new_prices} new prices (Total: {len(all_prices)})")
                
                # Stop if no new prices
                if new_prices == 0 and scroll_count > 0:
                    break
                
                # Scroll down
                pyautogui.scroll(-5)
                time.sleep(1)
                scroll_count += 1
            
            # If OCR found nothing, try AI Vision
            if len(all_prices) == 0 and self.ai_agent and self.ai_agent.initialized:
                self._log("[AI] OCR found no prices - using AI Vision to analyze...")
                ai_prices = self._extract_prices_with_ai()
                if ai_prices:
                    all_prices = ai_prices
            
            self._log(f"Extracted {len(all_prices)} total prices")
            return all_prices
            
        except Exception as e:
            self._log(f"OCR extraction failed: {e}", "error")
            return []
    
    def _extract_prices_with_ai(self) -> List[float]:
        """Use AI Vision to extract prices from screenshot when OCR fails."""
        if not self.ai_agent or not self.ai_agent.initialized:
            return []
        
        try:
            # Take fresh screenshot
            screenshot = pyautogui.screenshot()
            
            # Ask AI to find prices
            prompt = """Look at this Worldpac speedDIAL application screenshot.
Find ALL prices displayed (they should be in $ format like $12.50, $125.00 etc).

Analyze the screen and respond with ONLY a JSON object:
{
    "found_prices": [12.50, 125.00, 45.99],
    "diagnosis": "Found X prices in the parts list",
    "issue": null or "describe any issue you see"
}

If you cannot find any prices, explain why in the diagnosis and issue fields.
"""
            
            result = run_async_safe(self.ai_agent.find_element(screenshot, prompt))
            
            if not result.get("success"):
                # Try analyze_failure for diagnosis
                analysis = run_async_safe(self.ai_agent.analyze_failure(
                    screenshot,
                    "OCR cannot find prices on Worldpac screen",
                    "Expected to see price list with $ amounts"
                ))
                self._log(f"[AI] Diagnosis: {analysis.get('diagnosis', 'Unknown')}")
                self._log(f"[AI] Suggestion: {analysis.get('retry_strategy', 'None')}")
                return []
            
            # Parse prices from AI response
            reasoning = result.get("reasoning", "")
            self._log(f"[AI] {reasoning}")
            
            # Try to extract prices from the reasoning text
            price_pattern = r'\$?(\d+\.?\d{0,2})'
            matches = re.findall(price_pattern, reasoning)
            
            prices = []
            for m in matches:
                try:
                    price = float(m)
                    if 1.0 <= price <= 5000:
                        prices.append(price)
                except:
                    pass
            
            if prices:
                self._log(f"[AI] Found {len(prices)} prices: {prices[:5]}...")
            
            return prices
            
        except Exception as e:
            self._log(f"[AI] Price extraction error: {e}", "error")
            return []
    
    def get_prices_for_vin(self, vin: str, job: str) -> Dict:
        """
        Get prices for a VIN and job description.
        
        Args:
            vin: Vehicle Identification Number
            job: Job description (e.g., "Brake", "Engine Oil Leak")
        
        Returns:
            Dict with status and prices
        """
        result = {
            "success": False,
            "vin": vin,
            "job": job,
            "parts_selected": 0,
            "prices": [],
            "error": None
        }
        
        try:
            # Connect if needed
            if not self.connected:
                if not self.connect():
                    result["error"] = "Failed to connect to Worldpac"
                    return result
            
            # Step 1: Enter VIN
            if not self._enter_vin(vin):
                result["error"] = "VIN entry failed"
                return result
            
            # Step 2: Select vehicle
            if not self._select_vehicle():
                result["error"] = "Vehicle selection failed"
                return result
            
            # Step 3: Search job
            if not self._search_job(job):
                result["error"] = "Job search failed"
                return result
            
            # Step 4: Click search result
            if not self._click_search_result():
                result["error"] = "Result click failed"
                return result
            
            # Step 5: Select all parts
            parts = self._select_all_parts()
            result["parts_selected"] = parts
            
            if parts == 0:
                search_term = job.split()[0] if job else job
                result["error"] = f"No parts found for '{search_term}' in Worldpac. Try a different job description (e.g., 'Brake', 'Engine', 'Cooling')."
                result["no_parts_found"] = True  # Flag for frontend
                return result
            
            # Step 6: Click price button
            if not self._click_price_button():
                result["error"] = "Price button click failed"
                return result
            
            # Step 7: Extract prices via OCR (with AI fallback)
            prices = self._extract_prices_ocr()
            result["prices"] = prices
            
            if prices:
                result["success"] = True
                self._log(f"SUCCESS: Found {len(prices)} prices for {job}")
            else:
                # Use AI to diagnose why no prices were found
                if self.ai_agent and self.ai_agent.initialized:
                    self._log("[AI] Diagnosing price extraction failure...")
                    try:
                        screenshot = pyautogui.screenshot()
                        analysis = run_async_safe(self.ai_agent.analyze_failure(
                            screenshot,
                            "No prices found in Worldpac after clicking Price button",
                            f"VIN: {vin}, Job: {job}, Parts Selected: {parts}"
                        ))
                        diagnosis = analysis.get("diagnosis", "Unknown issue")
                        suggestion = analysis.get("retry_strategy", "None")
                        self._log(f"[AI] Problem: {diagnosis}")
                        self._log(f"[AI] Solution: {suggestion}")
                        result["ai_diagnosis"] = diagnosis
                        result["ai_suggestion"] = suggestion
                    except Exception as ai_err:
                        self._log(f"[AI] Diagnosis error: {ai_err}", "warning")
                
                result["error"] = "No prices extracted"
            
            return result
            
        except Exception as e:
            result["error"] = str(e)
            self._log(f"Error: {e}", "error")
            return result
    
    async def get_prices(self, part_numbers: List[str]) -> List[Dict]:
        """
        Legacy async interface for compatibility.
        
        Note: This method now requires VIN + job instead of part numbers.
        For proper usage, call get_prices_for_vin() directly.
        """
        self._log("get_prices() called - use get_prices_for_vin() for new flow")
        return []


# =============================================================================
# TEST FUNCTION
# =============================================================================
def test_worldpac():
    """Test the Worldpac automation."""
    print("=" * 60)
    print("WORLDPAC AUTOMATION TEST")
    print("=" * 60)
    
    wp = WorldpacAutomation()
    
    # Test with sample VIN and job
    vin = "WBA3B1C59FK456789"
    job = "Brake"
    
    print(f"\nVIN: {vin}")
    print(f"Job: {job}")
    print("-" * 60)
    
    result = wp.get_prices_for_vin(vin, job)
    
    print("\n" + "=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(f"Success: {result['success']}")
    print(f"Parts Selected: {result['parts_selected']}")
    print(f"Prices Found: {len(result['prices'])}")
    
    if result['prices']:
        print(f"Prices: {result['prices'][:10]}{'...' if len(result['prices']) > 10 else ''}")
    
    if result['error']:
        print(f"Error: {result['error']}")
    
    print("=" * 60)
    
    return result


if __name__ == "__main__":
    test_worldpac()
