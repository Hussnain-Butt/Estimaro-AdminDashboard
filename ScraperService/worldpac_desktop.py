"""
Worldpac speedDIAL Desktop Automation

This module automates the Worldpac speedDIAL desktop application
using pyautogui and pywinauto for price lookups.

Requirements:
    pip install pyautogui pywinauto pillow pyperclip

Usage:
    from worldpac_desktop import WorldpacAutomation
    wp = WorldpacAutomation()
    prices = await wp.get_prices(["ABC123", "DEF456"])
"""

import asyncio
import logging
import time
import re
from typing import List, Dict, Optional
from decimal import Decimal

# Try to import Windows automation libraries
try:
    import pyautogui
    import pywinauto
    from pywinauto import Application
    from pywinauto.keyboard import send_keys
    DESKTOP_AUTOMATION_AVAILABLE = True
except ImportError:
    DESKTOP_AUTOMATION_AVAILABLE = False
    pyautogui = None
    pywinauto = None

# Try to import clipboard library
try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False
    pyperclip = None

logger = logging.getLogger(__name__)


# =============================================================================
# COORDINATE CONSTANTS (Based on screenshots from user)
# These are RELATIVE to the Catalog window position
# Window position detected: (158, 123), Window size: 1228x690
# =============================================================================
CATALOG_COORDS = {
    # TOP ROW - "Vehicle | History | Mobile Scan | VIN field | search icon"
    # This row is around y=47 from top of Catalog window
    # VIN field is AFTER Mobile Scan dropdown, around x=270-380
    "vin_field": (320, 47),            # VIN input field center
    "vin_search_icon": (415, 47),      # Magnifying glass next to VIN
    
    # YEAR/MAKE/MODEL ROW - around y=75
    "year_dropdown": (140, 75),        # Year dropdown
    "make_dropdown": (290, 75),        # Make dropdown  
    "model_dropdown": (420, 75),       # Model dropdown
    
    # Vehicle selection popup (SEPARATE popup window - not relative to main catalog!)
    # This popup appears on top, need to detect its position separately
    "vehicle_row_first": (200, 55),    # Relative to POPUP window
    "ok_button": (587, 440),           # OK button in popup (relative to popup)
    
    # CATEGORY PANEL (left side) - "Category" tab and search field
    # Category tab row at y=105, search field at y=130
    "category_tab": (70, 105),         # "Category" tab
    "reset_button_top": (130, 105),    # "Reset" button next to Category
    "category_search": (150, 130),     # "Search part type name..." field
    
    # CATEGORY TREE - left panel, starts around y=160
    "oe_fluid_guide": (130, 165),      # OE Fluid Guide
    "replacement_parts": (130, 185),   # Replacement Parts (expandable)
    
    # MIDDLE PANEL - "Parts and Labor / Diagrams / Subcategories"
    # Tab row at y=105, content starts at y=130
    "parts_labor_tab": (400, 105),     # Parts and Labor tab
    "diagrams_tab": (480, 105),        # Diagrams tab
    "search_result_first": (400, 160), # First search result in middle panel
    "search_result_second": (400, 185),# Second result
    
    # RIGHT PANEL - Part Types / results grid
    # Starts around x=600
    "part_types_area": (700, 200),     # Part Types panel
    
    # PARTS DIAGRAM POPUP (when subcategory is clicked)
    # This is a separate popup, coordinates relative to that popup
    "checkbox_first": (400, 200),      # First checkbox in diagram popup
    "checkbox_second": (400, 220),     # Second checkbox
    "price_button_popup": (500, 380),  # Price button in diagram popup
    "save_button_popup": (340, 380),   # Save button
    "close_button_popup": (580, 380),  # Close button
    
    # BOTTOM ROW of main Catalog window - y=540 approx (690 height - 150)
    # "Selected: 0" | Price button | Reset button
    "selected_count": (550, 540),      # "Selected: 0" label
    "price_button": (610, 540),        # Main Price button  
    "reset_button": (710, 540),        # Reset button (bottom)
}



class WorldpacAutomation:
    """
    Automates Worldpac speedDIAL desktop application for price lookups.
    
    Flow:
    1. Enter VIN → Search → Select vehicle
    2. Search category → Click subcategory  
    3. Check parts → Click Price button
    4. Extract prices from clipboard/screen
    """
    
    def __init__(self):
        self.app = None
        self.main_window = None
        self.catalog_window = None
        self.connected = False
        
        # Window titles to search for
        self.main_title_pattern = ".*WORLDPAC speedDIAL.*"
        self.catalog_title_pattern = ".*Catalog.*"
        
        # Timing settings (seconds)
        self.click_delay = 0.3
        self.type_delay = 0.05
        self.wait_after_action = 1.0
        
        # Store window position for relative clicks
        self.win_left = 0
        self.win_top = 0
        
    def is_available(self) -> bool:
        """Check if desktop automation libraries are available."""
        return DESKTOP_AUTOMATION_AVAILABLE
    
    def connect(self) -> bool:
        """
        Connect to running Worldpac speedDIAL application.
        Returns True if successful.
        """
        if not DESKTOP_AUTOMATION_AVAILABLE:
            logger.error("Desktop automation libraries not installed. Run: pip install pyautogui pywinauto pillow pyperclip")
            return False
        
        try:
            logger.info("WORLDPAC: Attempting to connect to speedDIAL...")
            
            # Try to connect to existing speedDIAL window
            self.app = Application(backend="uia").connect(
                title_re=self.main_title_pattern,
                timeout=10
            )
            
            self.main_window = self.app.window(title_re=self.main_title_pattern)
            
            if self.main_window.exists():
                logger.info(f"WORLDPAC: Connected to {self.main_window.window_text()}")
                self.connected = True
                
                # Try to find and focus the Catalog window
                if self._find_catalog_window():
                    logger.info("WORLDPAC: Catalog window found and ready")
                    self.catalog_window.set_focus()
                    self._update_window_position()
                else:
                    logger.info("WORLDPAC: Catalog window not found, using main window")
                    self.main_window.set_focus()
                
                return True
            else:
                logger.error("WORLDPAC: Window found but not accessible")
                return False
                
        except Exception as e:
            logger.error(f"WORLDPAC: Failed to connect - {e}")
            return False
    
    def _update_window_position(self):
        """Update stored window position for relative click calculations."""
        try:
            target = self.catalog_window or self.main_window
            if target:
                rect = target.rectangle()
                self.win_left = rect.left
                self.win_top = rect.top
                self.win_width = rect.width()
                self.win_height = rect.height()
                logger.info(f"WORLDPAC: Window at ({self.win_left}, {self.win_top}), size {self.win_width}x{self.win_height}")
        except Exception as e:
            logger.warning(f"WORLDPAC: Could not update window position: {e}")
    
    def _ensure_window_foreground(self):
        """Ensure the Worldpac window is in foreground and focused."""
        try:
            target = self.catalog_window or self.main_window
            if target:
                # Restore if minimized
                try:
                    if target.is_minimized():
                        target.restore()
                        time.sleep(0.5)
                except:
                    pass
                
                # Set focus
                target.set_focus()
                time.sleep(0.3)
                
                # Update position after focus
                self._update_window_position()
                
                logger.info("WORLDPAC: Window brought to foreground")
                return True
        except Exception as e:
            logger.warning(f"WORLDPAC: Could not bring window to foreground: {e}")
        return False
    
    def _click_relative(self, coord_name: str, offset_x: int = 0, offset_y: int = 0, take_screenshot: bool = True):
        """Click at a position relative to the catalog window."""
        # Ensure window is focused first
        self._ensure_window_foreground()
        
        if coord_name in CATALOG_COORDS:
            rel_x, rel_y = CATALOG_COORDS[coord_name]
        else:
            rel_x, rel_y = 0, 0
            
        abs_x = self.win_left + rel_x + offset_x
        abs_y = self.win_top + rel_y + offset_y
        
        # Take screenshot before click for debugging
        if take_screenshot:
            self._save_screenshot(f'worldpac_before_{coord_name}.png')
        
        logger.info(f"WORLDPAC: Clicking {coord_name} at ({abs_x}, {abs_y})")
        pyautogui.click(abs_x, abs_y)
        time.sleep(self.click_delay)
    
    def _click_absolute(self, x: int, y: int, description: str = ""):
        """Click at absolute screen coordinates."""
        logger.info(f"WORLDPAC: Clicking {description} at ({x}, {y})")
        pyautogui.click(x, y)
        time.sleep(self.click_delay)
    
    def _type_text(self, text: str, clear_first: bool = True):
        """Type text with optional clearing first."""
        if clear_first:
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.1)
            pyautogui.press('delete')
            time.sleep(0.1)
        
        # Type character by character for reliability
        for char in text:
            pyautogui.typewrite(char, interval=self.type_delay)
        time.sleep(0.3)
    
    def _save_screenshot(self, filename: str):
        """Save a debug screenshot."""
        try:
            screenshot = pyautogui.screenshot()
            screenshot.save(filename)
            logger.info(f"WORLDPAC: Saved screenshot to {filename}")
        except Exception as e:
            logger.warning(f"WORLDPAC: Could not save screenshot: {e}")
    
    def _find_catalog_window(self) -> bool:
        """Find the Catalog popup window."""
        try:
            # Method 1: Look in all windows of the app
            windows = self.app.windows()
            logger.info(f"WORLDPAC: Found {len(windows)} windows in app")
            
            for win in windows:
                try:
                    title = win.window_text()
                    logger.info(f"WORLDPAC: Window: '{title}'")
                    if "Catalog" in title and "speedDIAL" in title:
                        self.catalog_window = win
                        logger.info(f"WORLDPAC: Found catalog window: {title}")
                        return True
                except:
                    continue
            
            # Method 2: Try to find as child of main window
            try:
                dialogs = self.main_window.children(control_type="Window")
                for d in dialogs:
                    title = d.window_text()
                    if "Catalog" in title:
                        self.catalog_window = d
                        logger.info(f"WORLDPAC: Found catalog as child: {title}")
                        return True
            except:
                pass
            
            # Method 3: Find by title pattern directly
            try:
                catalog_win = self.app.window(title_re=".*Catalog.*")
                if catalog_win.exists():
                    self.catalog_window = catalog_win
                    logger.info(f"WORLDPAC: Found catalog by pattern: {catalog_win.window_text()}")
                    return True
            except:
                pass
            
            return False
        except Exception as e:
            logger.warning(f"WORLDPAC: Error finding catalog window: {e}")
            return False
    
    def open_catalog(self) -> bool:
        """
        Open the catalog dialog by clicking the Catalog button.
        """
        try:
            # Check if catalog is already open
            if self._find_catalog_window():
                logger.info("WORLDPAC: Catalog already open")
                self._update_window_position()
                return True
            
            # Focus main window
            self.main_window.set_focus()
            time.sleep(0.5)
            
            # Click New Catalog & Results link (top right)
            rect = self.main_window.rectangle()
            catalog_x = rect.left + rect.width() - 100
            catalog_y = rect.top + 28
            
            logger.info(f"WORLDPAC: Clicking New Catalog at ({catalog_x}, {catalog_y})")
            pyautogui.click(catalog_x, catalog_y)
            time.sleep(2)
            
            # Check if catalog opened
            if self._find_catalog_window():
                self._update_window_position()
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"WORLDPAC: Could not open catalog - {e}")
            return False
    
    def _click_reset(self):
        """Click the Reset button to clear previous search."""
        self._update_window_position()
        self._click_relative("reset_button")
        time.sleep(1)
    
    def _enter_vin(self, vin: str) -> bool:
        """Enter VIN and search for vehicle."""
        try:
            self._update_window_position()
            
            # Click VIN field - need to click in the input area
            self._click_relative("vin_field", take_screenshot=True)
            time.sleep(0.5)
            
            # Triple-click to select all existing text, then delete
            pyautogui.click(clicks=3)
            time.sleep(0.2)
            pyautogui.press('delete')
            time.sleep(0.2)
            
            # Type VIN character by character
            logger.info(f"WORLDPAC: Typing VIN: {vin}")
            pyautogui.typewrite(vin, interval=0.05)
            time.sleep(0.5)
            logger.info(f"WORLDPAC: VIN entered: {vin}")
            
            # Click search icon (magnifying glass)
            self._click_relative("vin_search_icon", take_screenshot=True)
            time.sleep(4)  # Wait for vehicle popup to appear
            
            self._save_screenshot('worldpac_after_vin_search.png')
            return True
            
        except Exception as e:
            logger.error(f"WORLDPAC: VIN entry failed: {e}")
            return False
    
    def _find_refine_vehicle_popup(self):
        """
        Find the 'Refine Vehicle' popup window that appears after VIN search.
        This is a SEPARATE window from the main Catalog.
        Returns the popup window object or None.
        """
        try:
            # Look for popup with "Refine Vehicle" in title
            windows = self.app.windows()
            for win in windows:
                try:
                    title = win.window_text()
                    if "Refine" in title and "Vehicle" in title:
                        logger.info(f"WORLDPAC: Found Refine Vehicle popup: {title}")
                        return win
                except:
                    continue
            
            # Alternative: Look for any new popup window
            for win in windows:
                try:
                    title = win.window_text()
                    # Skip main window and catalog
                    if "speedDIAL for" in title and "Catalog" not in title:
                        continue
                    if "Catalog" in title and "Refine" not in title:
                        continue
                    # Check if it's a popup with vehicle list
                    if "speedDIAL" in title:
                        logger.info(f"WORLDPAC: Found potential popup: {title}")
                        return win
                except:
                    continue
                    
            return None
        except Exception as e:
            logger.warning(f"WORLDPAC: Error finding popup: {e}")
            return None
    
    def _select_vehicle(self) -> bool:
        """
        Select the first vehicle from the Refine Vehicle popup and click OK.
        The popup is a SEPARATE window - need to detect its position!
        """
        try:
            # First, try to find the Refine Vehicle popup
            popup = self._find_refine_vehicle_popup()
            
            if popup:
                # Get popup position
                popup_rect = popup.rectangle()
                popup_left = popup_rect.left
                popup_top = popup_rect.top
                popup_width = popup_rect.width()
                popup_height = popup_rect.height()
                
                logger.info(f"WORLDPAC: Refine popup at ({popup_left}, {popup_top}), size {popup_width}x{popup_height}")
                
                # Focus the popup
                popup.set_focus()
                time.sleep(0.3)
                
                # Click first vehicle row - relative to POPUP
                # First data row is around y=55-60 from popup top, x=center
                vehicle_x = popup_left + (popup_width // 2)
                vehicle_y = popup_top + 55
                
                self._save_screenshot('worldpac_before_vehicle_click.png')
                logger.info(f"WORLDPAC: Clicking vehicle at ({vehicle_x}, {vehicle_y})")
                pyautogui.click(vehicle_x, vehicle_y)
                time.sleep(0.5)
                
                # Double-click to select (some UIs need this)
                pyautogui.click(vehicle_x, vehicle_y)
                time.sleep(0.5)
                
                # Click OK button - bottom of popup, center-right area
                ok_x = popup_left + popup_width - 80
                ok_y = popup_top + popup_height - 30
                
                logger.info(f"WORLDPAC: Clicking OK at ({ok_x}, {ok_y})")
                pyautogui.click(ok_x, ok_y)
                time.sleep(2)
                
            else:
                # No popup found - maybe it auto-selected or closed
                # Try clicking OK button using main window coordinates
                logger.warning("WORLDPAC: Refine popup not found, trying fallback...")
                self._update_window_position()
                
                # The popup might be embedded - try clicking in the expected area
                # Based on user's screenshot, popup appears within catalog
                self._click_relative("vehicle_row_first", take_screenshot=True)
                time.sleep(0.5)
                self._click_relative("ok_button")
                time.sleep(2)
            
            self._save_screenshot('worldpac_after_vehicle_select.png')
            logger.info("WORLDPAC: Vehicle selection attempted")
            return True
            
        except Exception as e:
            logger.error(f"WORLDPAC: Vehicle selection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _search_category(self, category: str) -> bool:
        """Search for a category in the left panel."""
        try:
            self._update_window_position()
            
            # Click category search field
            self._click_relative("category_search")
            time.sleep(0.3)
            
            # Clear and type category
            self._type_text(category, clear_first=True)
            
            # Press Enter to search
            pyautogui.press('enter')
            time.sleep(2)
            
            self._save_screenshot('worldpac_after_category_search.png')
            logger.info(f"WORLDPAC: Searched for category: {category}")
            return True
            
        except Exception as e:
            logger.error(f"WORLDPAC: Category search failed: {e}")
            return False
    
    def _click_search_result(self) -> bool:
        """Click on the first search result in the middle panel."""
        try:
            self._update_window_position()
            
            # Click on first search result
            self._click_relative("search_result_first")
            time.sleep(2)
            
            self._save_screenshot('worldpac_after_result_click.png')
            logger.info("WORLDPAC: Clicked on search result")
            return True
            
        except Exception as e:
            logger.error(f"WORLDPAC: Result click failed: {e}")
            return False
    
    def _select_part_and_get_price(self) -> bool:
        """Check a part checkbox and click Price button."""
        try:
            self._update_window_position()
            
            # Click on first checkbox
            self._click_relative("checkbox_first")
            time.sleep(0.5)
            
            # Click Price button (in popup)
            self._click_relative("price_button_popup")
            time.sleep(3)
            
            self._save_screenshot('worldpac_after_price_click.png')
            logger.info("WORLDPAC: Clicked Price button")
            return True
            
        except Exception as e:
            logger.error(f"WORLDPAC: Price button click failed: {e}")
            return False
    
    def _extract_prices_clipboard(self) -> List[Dict]:
        """
        Extract prices using clipboard method.
        Tries to select all visible text and parse prices.
        """
        prices = []
        
        if not CLIPBOARD_AVAILABLE:
            logger.warning("WORLDPAC: pyperclip not available, skipping clipboard extraction")
            return prices
        
        try:
            # Try to select all and copy
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            pyautogui.hotkey('ctrl', 'c')
            time.sleep(0.3)
            
            # Read from clipboard
            text = pyperclip.paste()
            
            if text:
                logger.info(f"WORLDPAC: Got clipboard text ({len(text)} chars)")
                
                # Find price patterns ($XX.XX format)
                price_pattern = r'\$(\d+(?:,\d{3})*\.?\d*)'
                matches = re.findall(price_pattern, text)
                
                for i, price_str in enumerate(matches):
                    try:
                        # Remove commas and convert to Decimal
                        clean_price = price_str.replace(',', '')
                        price_val = Decimal(clean_price)
                        
                        # Filter reasonable prices ($0.01 - $10,000)
                        if Decimal('0.01') <= price_val <= Decimal('10000'):
                            prices.append({
                                "part_number": f"WORLDPAC_PART_{i+1}",
                                "price": price_val,
                                "vendor": "Worldpac",
                                "stock_status": "Available"
                            })
                            logger.info(f"WORLDPAC: Found price ${price_val}")
                    except:
                        continue
            
            logger.info(f"WORLDPAC: Extracted {len(prices)} prices from clipboard")
            
        except Exception as e:
            logger.error(f"WORLDPAC: Clipboard extraction failed: {e}")
        
        return prices
    
    def _extract_prices_screen(self) -> List[Dict]:
        """
        Extract prices by scanning screen for price patterns.
        Uses pywinauto to find text controls.
        """
        prices = []
        
        try:
            target = self.catalog_window or self.main_window
            if not target:
                return prices
            
            # Try to find all text elements
            all_texts = []
            
            try:
                for el in target.descendants():
                    try:
                        text = el.window_text()
                        if text and "$" in text:
                            all_texts.append(text)
                    except:
                        continue
            except:
                pass
            
            logger.info(f"WORLDPAC: Found {len(all_texts)} text elements with $")
            
            # Parse prices from text
            price_pattern = r'\$(\d+(?:,\d{3})*\.?\d*)'
            
            for text in all_texts:
                matches = re.findall(price_pattern, text)
                for price_str in matches:
                    try:
                        clean_price = price_str.replace(',', '')
                        price_val = Decimal(clean_price)
                        
                        if Decimal('0.01') <= price_val <= Decimal('10000'):
                            prices.append({
                                "part_number": f"WORLDPAC_PART",
                                "price": price_val,
                                "vendor": "Worldpac",
                                "stock_status": "Available"
                            })
                            logger.info(f"WORLDPAC: Found price ${price_val} in screen text")
                    except:
                        continue
            
        except Exception as e:
            logger.error(f"WORLDPAC: Screen extraction failed: {e}")
        
        return prices
    
    def search_with_vin_and_job(self, vin: str, job_description: str) -> List[Dict]:
        """
        Complete Worldpac search flow:
        1. Open Catalog dialog (if not open)
        2. Reset previous search
        3. Enter VIN → Search → Select vehicle
        4. Search category → Click subcategory
        5. Check parts → Click Price button
        6. Extract prices
        """
        results = []
        
        try:
            if not self.connected:
                if not self.connect():
                    return results
            
            # =========================================
            # STEP 1: Open/Find Catalog
            # =========================================
            logger.info("WORLDPAC: Opening Catalog dialog...")
            if not self.open_catalog():
                logger.warning("WORLDPAC: Could not open Catalog dialog")
            
            time.sleep(1)
            self._update_window_position()
            
            # =========================================
            # STEP 2: Reset previous search
            # =========================================
            logger.info("WORLDPAC: Clicking Reset...")
            self._click_reset()
            time.sleep(1)
            
            # =========================================
            # STEP 3: Enter VIN and search
            # =========================================
            logger.info(f"WORLDPAC: Entering VIN: {vin}")
            if not self._enter_vin(vin):
                logger.error("WORLDPAC: VIN entry failed")
                return results
            
            # =========================================
            # STEP 4: Select vehicle from popup
            # =========================================
            logger.info("WORLDPAC: Selecting vehicle...")
            if not self._select_vehicle():
                logger.warning("WORLDPAC: Vehicle selection may have failed")
            
            time.sleep(1)
            self._update_window_position()
            
            # =========================================
            # STEP 5: Search for category/job
            # =========================================
            # Map job description to category keywords
            job_lower = job_description.lower()
            category = job_description  # Default: use as-is
            
            # Smart category mapping
            if "oil" in job_lower:
                category = "Oil"
            elif "brake" in job_lower:
                category = "Brake"
            elif "engine" in job_lower:
                category = "Engine"
            elif "air" in job_lower or "filter" in job_lower:
                category = "Air Filter"
            elif "coolant" in job_lower or "radiator" in job_lower:
                category = "Cooling"
            
            logger.info(f"WORLDPAC: Searching category: {category}")
            if not self._search_category(category):
                logger.warning("WORLDPAC: Category search failed")
            
            # =========================================
            # STEP 6: Click on first search result
            # =========================================
            logger.info("WORLDPAC: Clicking search result...")
            if not self._click_search_result():
                logger.warning("WORLDPAC: Could not click search result")
            
            time.sleep(2)
            
            # =========================================
            # STEP 7: Select part and click Price
            # =========================================
            logger.info("WORLDPAC: Selecting part and clicking Price...")
            if not self._select_part_and_get_price():
                logger.warning("WORLDPAC: Price button click failed")
            
            time.sleep(2)
            
            # =========================================
            # STEP 8: Extract prices
            # =========================================
            logger.info("WORLDPAC: Extracting prices...")
            
            # Try clipboard method first
            results = self._extract_prices_clipboard()
            
            # If clipboard failed, try screen method
            if not results:
                logger.info("WORLDPAC: Clipboard method failed, trying screen extraction...")
                results = self._extract_prices_screen()
            
            # Save final screenshot
            self._save_screenshot('worldpac_final_result.png')
            
            logger.info(f"WORLDPAC: Search complete - found {len(results)} prices")
            return results
            
        except Exception as e:
            logger.error(f"WORLDPAC: Search flow failed - {e}")
            import traceback
            logger.error(traceback.format_exc())
            return results
    
    async def get_prices(self, part_numbers: List[str], vin: str = None, job_description: str = None) -> List[Dict]:
        """
        Get prices for parts from Worldpac.
        
        If VIN and job_description are provided, uses the complete search flow.
        Otherwise, attempts part number search (less reliable).
        """
        results = []
        
        if not self.is_available():
            logger.error("WORLDPAC: Desktop automation not available")
            return results
        
        if not self.connected:
            if not self.connect():
                logger.error("WORLDPAC: Could not connect to speedDIAL")
                return results
        
        # If we have VIN and job, use the complete flow
        if vin and job_description:
            logger.info(f"WORLDPAC: Using VIN+Job search: VIN={vin}, Job={job_description}")
            results = self.search_with_vin_and_job(vin, job_description)
        else:
            # Fallback: Try part number search
            logger.info("WORLDPAC: No VIN provided, attempting part number search")
            for part_num in part_numbers:
                try:
                    result = self.search_part_number(part_num)
                    if result:
                        results.append(result)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"WORLDPAC: Error getting price for {part_num} - {e}")
        
        logger.info(f"WORLDPAC: Found {len(results)} prices out of {len(part_numbers)} parts")
        return results
    
    def search_part_number(self, part_number: str) -> Optional[Dict]:
        """
        Search for a specific part number (fallback method).
        """
        try:
            if not self.connected:
                if not self.connect():
                    return None
            
            self._find_catalog_window()
            self._update_window_position()
            
            # Click category search
            self._click_relative("category_search")
            time.sleep(0.3)
            
            # Type part number
            self._type_text(part_number, clear_first=True)
            pyautogui.press('enter')
            time.sleep(2)
            
            # Try to extract prices
            prices = self._extract_prices_clipboard()
            if not prices:
                prices = self._extract_prices_screen()
            
            if prices:
                return prices[0]
            
            return None
            
        except Exception as e:
            logger.error(f"WORLDPAC: Part search failed - {e}")
            return None
    
    def click_price_button(self) -> bool:
        """Click the main Price button at bottom."""
        try:
            self._update_window_position()
            self._click_relative("price_button")
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"WORLDPAC: Could not click Price button - {e}")
            return False


# Singleton instance
worldpac_automation = WorldpacAutomation()


# Test function
async def test_worldpac():
    """Test Worldpac automation."""
    wp = WorldpacAutomation()
    
    print("Testing Worldpac Desktop Automation...")
    print(f"Libraries available: {wp.is_available()}")
    print(f"Clipboard available: {CLIPBOARD_AVAILABLE}")
    
    if wp.is_available():
        print("Connecting to speedDIAL...")
        connected = wp.connect()
        print(f"Connected: {connected}")
        
        if connected:
            print("Testing VIN + Job search...")
            results = await wp.get_prices(
                ["TEST"],
                vin="WBA3A5C55CF256987",
                job_description="Oil"
            )
            print(f"Results: {results}")


def debug_coordinates():
    """
    Debug function to visualize where clicks will happen.
    Takes a screenshot with red dots at click positions.
    
    Run from RDP server:
        cd ScraperService
        python -c "from worldpac_desktop import debug_coordinates; debug_coordinates()"
    """
    if not DESKTOP_AUTOMATION_AVAILABLE:
        print("ERROR: pyautogui/pywinauto not installed!")
        return
    
    from PIL import Image, ImageDraw
    
    wp = WorldpacAutomation()
    print("Connecting to Worldpac...")
    
    if not wp.connect():
        print("ERROR: Could not connect to Worldpac speedDIAL!")
        print("Make sure the application is running.")
        return
    
    wp._find_catalog_window()
    wp._update_window_position()
    
    print(f"Window position: ({wp.win_left}, {wp.win_top})")
    print(f"Window size: {wp.win_width}x{wp.win_height}")
    
    # Take screenshot
    screenshot = pyautogui.screenshot()
    draw = ImageDraw.Draw(screenshot)
    
    # Draw red circles at each coordinate position
    for name, (rel_x, rel_y) in CATALOG_COORDS.items():
        abs_x = wp.win_left + rel_x
        abs_y = wp.win_top + rel_y
        
        # Draw a red circle
        radius = 8
        draw.ellipse(
            [abs_x - radius, abs_y - radius, abs_x + radius, abs_y + radius],
            fill='red',
            outline='yellow',
            width=2
        )
        
        # Draw label
        draw.text((abs_x + 10, abs_y - 5), name[:15], fill='yellow')
        
        print(f"  {name}: ({abs_x}, {abs_y})")
    
    # Save debug image
    screenshot.save('worldpac_debug_coordinates.png')
    print("\nSaved: worldpac_debug_coordinates.png")
    print("Open this image to verify click positions are correct!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        debug_coordinates()
    else:
        asyncio.run(test_worldpac())

