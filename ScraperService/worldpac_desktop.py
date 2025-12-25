"""
Worldpac speedDIAL Desktop Automation

This module automates the Worldpac speedDIAL desktop application
using pyautogui and pywinauto for price lookups.

Requirements:
    pip install pyautogui pywinauto pillow

Usage:
    from worldpac_desktop import WorldpacAutomation
    wp = WorldpacAutomation()
    prices = await wp.get_prices(["ABC123", "DEF456"])
"""

import asyncio
import logging
import time
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

logger = logging.getLogger(__name__)


class WorldpacAutomation:
    """
    Automates Worldpac speedDIAL desktop application for price lookups.
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
        
    def is_available(self) -> bool:
        """Check if desktop automation libraries are available."""
        return DESKTOP_AUTOMATION_AVAILABLE
    
    def connect(self) -> bool:
        """
        Connect to running Worldpac speedDIAL application.
        Returns True if successful.
        """
        if not DESKTOP_AUTOMATION_AVAILABLE:
            logger.error("Desktop automation libraries not installed. Run: pip install pyautogui pywinauto pillow")
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
        Tries multiple positions where the Catalog button might be.
        """
        try:
            # Check if catalog is already open
            if self._find_catalog_window():
                logger.info("WORLDPAC: Catalog already open")
                return True
            
            # Focus main window
            self.main_window.set_focus()
            time.sleep(0.5)
            
            # Get main window rectangle
            rect = self.main_window.rectangle()
            win_left = rect.left
            win_top = rect.top
            win_width = rect.width()
            win_height = rect.height()
            
            logger.info(f"WORLDPAC: Main window at ({win_left}, {win_top}), size {win_width}x{win_height}")
            
            # Save debug screenshot BEFORE clicking
            screenshot = pyautogui.screenshot()
            screenshot.save('worldpac_before_catalog_click.png')
            logger.info("WORLDPAC: Saved pre-click screenshot to worldpac_before_catalog_click.png")
            
            # USER MEASURED EXACT POSITION:
            # Catalog button at X≈780, Y≈95 from 2048×1098 screenshot
            # Window-relative position (if window at 39, 21): X=780-39=741, Y=95-21=74
            
            # List of positions to try for Catalog button
            click_positions = [
                # Position 1: USER'S EXACT MEASURED POSITION (absolute screen coords)
                (780, 95, "USER MEASURED: absolute (780, 95)"),
                
                # Position 2: Window-relative calculation
                # If window at (39, 21): 780-39=741, 95-21=74
                (win_left + 741, win_top + 74, "Window-relative (741, 74)"),
                
                # Position 3: Slight variations for DPI scaling (125% = 0.8x)
                (int(780 * 0.8), int(95 * 0.8), "DPI scaled 0.8x (624, 76)"),
                
                # Position 4: "New Catalog & Results" link at top right
                (win_left + win_width - 80, win_top + 18, "New Catalog & Results link"),
                
                # Position 5: Center of catalog icon area based on user description
                # "Between DC Direct and Replacement Parts, under banner"
                (win_left + 400, win_top + 55, "Toolbar center estimate"),
            ]
            
            for x, y, description in click_positions:
                logger.info(f"WORLDPAC: Trying click at ({x}, {y}) - {description}")
                pyautogui.click(x, y)
                time.sleep(2)
                
                # Check if catalog opened
                if self._find_catalog_window():
                    logger.info(f"WORLDPAC: Catalog opened with {description}!")
                    return True
            
            # If all positions failed, try double-clicking
            logger.info("WORLDPAC: Trying double-click on Catalog button")
            pyautogui.doubleClick(win_left + 360, win_top + 55)
            time.sleep(2)
            
            if self._find_catalog_window():
                logger.info("WORLDPAC: Catalog opened with double-click!")
                return True
            
            # Save failure screenshot
            screenshot = pyautogui.screenshot()
            screenshot.save('worldpac_catalog_click_failed.png')
            logger.warning("WORLDPAC: All catalog click attempts failed - saved worldpac_catalog_click_failed.png")
            
            return False
            
        except Exception as e:
            logger.warning(f"WORLDPAC: Could not open catalog - {e}")
            return False
    
    def search_by_vin(self, vin: str) -> bool:
        """
        Search for vehicle by VIN.
        """
        try:
            if not self.connected:
                if not self.connect():
                    return False
            
            self._find_catalog_window()
            target = self.catalog_window or self.main_window
            target.set_focus()
            time.sleep(0.3)
            
            # Find VIN field - look for text "VIN" near an edit control
            # Use pyautogui to type in the VIN field
            
            # Method 1: Use Tab to navigate to VIN field
            # The VIN field appears to be after Year/Make/Model dropdowns
            
            # Find and click on VIN field using image recognition or coordinates
            # For now, use keyboard navigation
            
            logger.info(f"WORLDPAC: Entering VIN: {vin}")
            
            # Try to find VIN edit control
            vin_fields = target.descendants(control_type="Edit")
            for field in vin_fields:
                try:
                    # Check if field placeholder contains "VIN"
                    field.set_focus()
                    field.type_keys("^a")  # Select all
                    field.type_keys(vin, with_spaces=True)
                    time.sleep(0.5)
                    field.type_keys("{ENTER}")
                    logger.info("WORLDPAC: VIN entered successfully")
                    time.sleep(2)  # Wait for results
                    return True
                except:
                    continue
            
            # Fallback: use pyautogui
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.typewrite(vin, interval=0.05)
            pyautogui.press('enter')
            time.sleep(2)
            return True
            
        except Exception as e:
            logger.error(f"WORLDPAC: VIN search failed - {e}")
            return False
    
    def search_by_ymm(self, year: str, make: str, model: str) -> bool:
        """
        Search for vehicle by Year/Make/Model.
        """
        try:
            if not self.connected:
                if not self.connect():
                    return False
            
            self._find_catalog_window()
            target = self.catalog_window or self.main_window
            target.set_focus()
            time.sleep(0.3)
            
            logger.info(f"WORLDPAC: Searching for {year} {make} {model}")
            
            # Find Year dropdown
            year_combo = target.child_window(title="Year", control_type="ComboBox")
            if year_combo.exists():
                year_combo.select(year)
                time.sleep(0.5)
            
            # Find Make dropdown
            make_combo = target.child_window(title="Make", control_type="ComboBox")
            if make_combo.exists():
                make_combo.select(make)
                time.sleep(0.5)
            
            # Find Model dropdown  
            model_combo = target.child_window(title="Model", control_type="ComboBox")
            if model_combo.exists():
                model_combo.select(model)
                time.sleep(0.5)
            
            # Click Refine button
            refine_btn = target.child_window(title="Refine", control_type="Button")
            if refine_btn.exists():
                refine_btn.click()
                time.sleep(2)
            
            logger.info("WORLDPAC: YMM search completed")
            return True
            
        except Exception as e:
            logger.error(f"WORLDPAC: YMM search failed - {e}")
            return False
    
    def search_part_category(self, category: str) -> bool:
        """
        Click on a category in the parts tree (e.g., "Brake").
        """
        try:
            target = self.catalog_window or self.main_window
            target.set_focus()
            
            # Find the search box
            search_box = target.child_window(
                control_type="Edit",
                found_index=0  # First edit box after vehicle selection
            )
            
            if search_box.exists():
                search_box.set_focus()
                search_box.type_keys("^a")  # Select all
                search_box.type_keys(category, with_spaces=True)
                time.sleep(1)
                
                # Click on first matching result in tree
                tree = target.child_window(control_type="Tree")
                if tree.exists():
                    items = tree.descendants(control_type="TreeItem")
                    for item in items:
                        if category.lower() in item.window_text().lower():
                            item.click_input()
                            logger.info(f"WORLDPAC: Clicked on category: {item.window_text()}")
                            time.sleep(1)
                            return True
            
            return False
            
        except Exception as e:
            logger.error(f"WORLDPAC: Category search failed - {e}")
            return False
    
    def search_part_number(self, part_number: str) -> Optional[Dict]:
        """
        Search for a specific part number and extract price.
        Uses pyautogui for reliable input in speedDIAL.
        """
        try:
            if not self.connected:
                if not self.connect():
                    return None
            
            # IMPORTANT: Always refresh the catalog window reference
            self._find_catalog_window()
            
            target = self.catalog_window if self.catalog_window else self.main_window
            
            try:
                target.set_focus()
            except Exception as e:
                logger.warning(f"WORLDPAC: Could not set focus: {e}")
            
            time.sleep(0.5)
            
            # Log window info for debugging
            logger.info(f"WORLDPAC: Searching for part {part_number}")
            logger.info(f"WORLDPAC: Using window: {target.window_text() if target else 'None'}")
            
            # Method 1: Try to find any Edit control and use it
            found_search = False
            edit_controls = target.descendants(control_type="Edit")
            
            logger.info(f"WORLDPAC: Found {len(edit_controls)} edit controls")
            
            for i, edit in enumerate(edit_controls):
                try:
                    edit_text = edit.window_text() or ""
                    logger.debug(f"WORLDPAC: Edit {i}: '{edit_text[:50] if edit_text else 'empty'}'")
                    
                    # Look for search-related edit controls
                    # Skip VIN and year fields
                    if "vin" in edit_text.lower():
                        continue
                    if edit_text.strip().isdigit() and len(edit_text.strip()) == 4:
                        continue  # Skip year field
                    
                    # Try to use this edit control
                    edit.set_focus()
                    time.sleep(0.2)
                    
                    # Clear and type part number
                    edit.type_keys("^a")  # Select all
                    time.sleep(0.1)
                    edit.type_keys(part_number, with_spaces=True)
                    time.sleep(0.1)
                    edit.type_keys("{ENTER}")
                    
                    found_search = True
                    logger.info(f"WORLDPAC: Entered part in edit control {i}")
                    time.sleep(2)  # Wait for results
                    break
                    
                except Exception as e:
                    logger.debug(f"WORLDPAC: Edit {i} failed: {e}")
                    continue
            
            # Method 2: Use pyautogui with window position
            if not found_search:
                logger.info("WORLDPAC: Using pyautogui with screen coordinates")
                
                try:
                    # Get window rectangle
                    rect = target.rectangle()
                    win_left = rect.left
                    win_top = rect.top
                    win_width = rect.width()
                    win_height = rect.height()
                    
                    logger.info(f"WORLDPAC: Catalog window at ({win_left}, {win_top}), size {win_width}x{win_height}")
                    
                    # Based on the screenshot, the search field "Search part type name" is:
                    # - Left side of the catalog window
                    # - About 170px from left edge
                    # - About 220px from top of the dialog
                    
                    search_x = win_left + 170
                    search_y = win_top + 220
                    
                    logger.info(f"WORLDPAC: Clicking search field at ({search_x}, {search_y})")
                    
                    # First, click Reset button to clear previous search (bottom right)
                    reset_x = win_left + win_width - 50
                    reset_y = win_top + win_height - 50
                    pyautogui.click(reset_x, reset_y)
                    time.sleep(1)
                    
                    # Click on the search field
                    pyautogui.click(search_x, search_y)
                    time.sleep(0.3)
                    
                    # Clear and type
                    pyautogui.hotkey('ctrl', 'a')
                    time.sleep(0.1)
                    
                    # Type the search term (use job description for Worldpac, not part number)
                    # Worldpac searches by part TYPE, not part NUMBER
                    pyautogui.typewrite(part_number.replace('_', ''), interval=0.03)
                    time.sleep(0.5)
                    
                    pyautogui.press('enter')
                    time.sleep(2)
                    
                    found_search = True
                    logger.info("WORLDPAC: Typed search term using screen coordinates")
                    
                except Exception as e:
                    logger.error(f"WORLDPAC: Screen coordinate method failed: {e}")
            
            # Extract price from results - use screen capture method
            price = self._extract_price_from_screen(target)
            
            if price:
                return {
                    "part_number": part_number,
                    "price": price,
                    "vendor": "Worldpac",
                    "stock_status": "Available"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"WORLDPAC: Part search failed - {e}")
            return None
    
    def _extract_price_from_window(self, window) -> Optional[Decimal]:
        """
        Extract price from the current window.
        Scans all text elements for $ patterns.
        """
        try:
            import re
            
            # Get all text elements from window
            all_texts = []
            
            # Method 1: Get from descendants
            try:
                for el in window.descendants():
                    try:
                        text = el.window_text()
                        if text and "$" in text:
                            all_texts.append(text)
                    except:
                        continue
            except:
                pass
            
            # Method 2: Also check Static and Text controls specifically
            try:
                statics = window.descendants(control_type="Text")
                for s in statics:
                    try:
                        text = s.window_text()
                        if text and "$" in text:
                            all_texts.append(text)
                    except:
                        continue
            except:
                pass
            
            logger.info(f"WORLDPAC: Found {len(all_texts)} text elements with $ symbol")
            
            # Find price patterns - look for realistic prices ($5.00 - $999.99)
            price_pattern = r'\$(\d+\.?\d*)'
            prices_found = []
            
            for text in all_texts:
                matches = re.findall(price_pattern, text)
                for match in matches:
                    try:
                        price = Decimal(match)
                        # Filter out unrealistic prices
                        if price > 0 and price < 10000:
                            prices_found.append(price)
                            logger.info(f"WORLDPAC: Found price ${price} in '{text[:30]}...'")
                    except:
                        continue
            
            if prices_found:
                # Return the first reasonable price (usually the main price)
                best_price = min(prices_found)  # Get cheapest
                logger.info(f"WORLDPAC: Best price for part: ${best_price}")
                return best_price
            
            return None
            
        except Exception as e:
            logger.error(f"WORLDPAC: Price extraction failed - {e}")
            return None
    
    def _extract_price_from_screen(self, window) -> Optional[Decimal]:
        """
        Extract price from screen using screenshot and OCR.
        Falls back to window-based extraction as pywinauto reports 0 UI elements.
        """
        try:
            import re
            from PIL import Image
            
            # Get window rectangle for screenshot
            rect = window.rectangle()
            
            # Take screenshot of the window area
            screenshot = pyautogui.screenshot(region=(
                rect.left, rect.top, 
                rect.width(), rect.height()
            ))
            
            # Save screenshot for debugging
            screenshot.save('worldpac_debug.png')
            logger.info("WORLDPAC: Saved debug screenshot to worldpac_debug.png")
            
            # Try to find prices in the screenshot using simple pattern matching
            # For now, we'll try to read any text that looks like prices
            
            # Since we can't do OCR without pytesseract, let's try alternative methods
            
            # Method 1: Check if the Price button shows any value
            # The Price button in bottom-right might have a price after clicking
            
            # For now, fall back to the window-based extraction
            return self._extract_price_from_window(window)
            
        except Exception as e:
            logger.error(f"WORLDPAC: Screen extraction failed - {e}")
            # Fall back to window method
            return self._extract_price_from_window(window)
    
    def search_with_vin_and_job(self, vin: str, job_description: str) -> List[Dict]:
        """
        Complete Worldpac search flow:
        0. Open Catalog dialog from main window (NEW!)
        1. Enter VIN
        2. Click search
        3. Handle vehicle selection popup (click Ok)
        4. Enter job description in search field
        5. Wait for results
        6. Extract prices
        """
        results = []
        
        try:
            if not self.connected:
                if not self.connect():
                    return results
            
            # =========================================
            # STEP 0: Open Catalog dialog first!
            # =========================================
            logger.info("WORLDPAC: Opening Catalog dialog from main window...")
            if not self.open_catalog():
                logger.warning("WORLDPAC: Could not open Catalog dialog")
                # Continue anyway, maybe it's already in the right state
            
            time.sleep(1)
            
            # Refresh catalog window reference
            self._find_catalog_window()
            target = self.catalog_window if self.catalog_window else self.main_window
            
            # Get window rectangle
            rect = target.rectangle()
            win_left = rect.left
            win_top = rect.top
            win_width = rect.width()
            win_height = rect.height()
            
            logger.info(f"WORLDPAC: Catalog at ({win_left}, {win_top}), size {win_width}x{win_height}")
            
            # Focus the window
            try:
                target.set_focus()
            except:
                pass
            time.sleep(0.5)
            
            # =========================================
            # NEW APPROACH: Use KEYBOARD NAVIGATION instead of clicks!
            # This is more reliable for desktop apps
            # =========================================
            
            # =========================================
            # STEP 1: Click Reset button to clear
            # =========================================
            reset_x = win_left + win_width - 50
            reset_y = win_top + win_height - 40
            logger.info(f"WORLDPAC: Clicking Reset at ({reset_x}, {reset_y})")
            pyautogui.click(reset_x, reset_y)
            time.sleep(2)
            
            # =========================================
            # STEP 2: Navigate to VIN field using TAB key
            # After Reset, focus should be at top of form
            # Press Tab multiple times to reach VIN field
            # =========================================
            logger.info("WORLDPAC: Navigating to VIN field using Tab key...")
            
            # Click somewhere in the Vehicle section to start
            vehicle_section_x = win_left + 100
            vehicle_section_y = win_top + 80
            pyautogui.click(vehicle_section_x, vehicle_section_y)
            time.sleep(0.5)
            
            # Tab through: Vehicle tab → History dropdown → Mobile Scan → VIN field
            # Usually VIN is 3-4 tabs from start
            for i in range(4):
                pyautogui.press('tab')
                time.sleep(0.2)
            
            logger.info("WORLDPAC: Should be in VIN field now, typing VIN...")
            
            # Clear any existing content and type VIN
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.1)
            pyautogui.typewrite(vin, interval=0.05)
            time.sleep(0.5)
            
            logger.info(f"WORLDPAC: Entered VIN: {vin}")
            
            # =========================================
            # STEP 3: Press Tab to move to search button, then Enter
            # Or just press Enter if VIN field auto-searches
            # =========================================
            logger.info("WORLDPAC: Pressing Tab then Enter to search...")
            pyautogui.press('tab')  # Move to search button
            time.sleep(0.3)
            pyautogui.press('enter')  # Click search
            time.sleep(4)  # Wait for vehicle popup
            
            # Save screenshot after VIN search
            pyautogui.screenshot().save('worldpac_after_vin_search.png')
            logger.info("WORLDPAC: Saved screenshot after VIN search")
            
            # =========================================
            # STEP 4: Handle vehicle selection popup
            # Popup should appear - press Enter to select first vehicle
            # =========================================
            logger.info("WORLDPAC: Handling vehicle popup with Enter key...")
            
            # Try to find popup window
            popup_found = False
            try:
                for win in self.app.windows():
                    title = win.window_text()
                    if "Refine" in title or "Vehicle" in title:
                        logger.info(f"WORLDPAC: Found popup: {title}")
                        popup_found = True
                        break
            except:
                pass
            
            if popup_found:
                logger.info("WORLDPAC: Popup found - pressing Enter to select vehicle")
                pyautogui.press('enter')
                time.sleep(2)
            else:
                logger.info("WORLDPAC: No popup detected - trying Enter anyway")
                pyautogui.press('enter')
                time.sleep(2)
            
            # Save screenshot after vehicle selection
            pyautogui.screenshot().save('worldpac_after_vehicle_select.png')
            logger.info("WORLDPAC: Saved screenshot after vehicle selection")
            
            # Refresh window reference
            self._find_catalog_window()
            target = self.catalog_window if self.catalog_window else self.main_window
            
            # =========================================
            # STEP 5: Navigate to Category search field
            # Click in the Category section, then type
            # =========================================
            logger.info("WORLDPAC: Navigating to Category search field...")
            
            # Click in Category search area (left side panel)
            rect = target.rectangle()
            category_x = rect.left + 165
            category_y = rect.top + 175
            
            logger.info(f"WORLDPAC: Clicking Category search at ({category_x}, {category_y})")
            pyautogui.click(category_x, category_y)
            time.sleep(0.5)
            
            # Clear and type job description
            pyautogui.hotkey('ctrl', 'a')
            time.sleep(0.2)
            
            job_clean = ''.join(c for c in job_description if c.isalnum() or c == ' ')
            pyautogui.typewrite(job_clean.replace(' ', ''), interval=0.05)
            time.sleep(0.5)
            
            # Press Enter to search
            pyautogui.press('enter')
            time.sleep(3)
            
            logger.info(f"WORLDPAC: Searched for job: {job_clean}")
            
            # =========================================
            # STEP 6: Save debug screenshot
            # =========================================
            screenshot = pyautogui.screenshot()
            screenshot.save('worldpac_search_result.png')
            logger.info("WORLDPAC: Saved screenshot to worldpac_search_result.png")
            
            # =========================================
            # STEP 7: Try to extract prices from screen text
            # =========================================
            # Since pywinauto can't see controls, we'll report that search was done
            # User can verify from screenshot
            
            # For now, return a placeholder indicating search was performed
            # Real price extraction would need OCR (pytesseract)
            logger.info("WORLDPAC: Search completed - check worldpac_search_result.png for results")
            
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
            # Try part number search (less reliable for Worldpac)
            for part_num in part_numbers:
                try:
                    result = self.search_part_number(part_num)
                    if result:
                        results.append(result)
                    else:
                        logger.warning(f"WORLDPAC: No price found for {part_num}")
                    
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"WORLDPAC: Error getting price for {part_num} - {e}")
        
        logger.info(f"WORLDPAC: Found {len(results)} prices out of {len(part_numbers)} parts")
        return results
    
    def click_price_button(self) -> bool:
        """Click the Price button to get pricing."""
        try:
            target = self.catalog_window or self.main_window
            rect = target.rectangle()
            
            # Price button is in bottom right corner
            price_x = rect.left + rect.width() - 100
            price_y = rect.top + rect.height() - 40
            
            logger.info(f"WORLDPAC: Clicking Price button at ({price_x}, {price_y})")
            pyautogui.click(price_x, price_y)
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
    
    if wp.is_available():
        print("Connecting to speedDIAL...")
        connected = wp.connect()
        print(f"Connected: {connected}")
        
        if connected:
            print("Testing VIN search...")
            wp.search_by_vin("WBAKN9C56ED682076")


if __name__ == "__main__":
    asyncio.run(test_worldpac())
