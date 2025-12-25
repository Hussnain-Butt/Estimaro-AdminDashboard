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
                
                # Bring window to front
                try:
                    self.main_window.set_focus()
                except:
                    pass
                
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
            # Look for catalog window
            windows = self.app.windows()
            for win in windows:
                title = win.window_text()
                if "Catalog" in title:
                    self.catalog_window = win
                    logger.info(f"WORLDPAC: Found catalog window: {title}")
                    return True
            return False
        except:
            return False
    
    def open_catalog(self) -> bool:
        """Open the catalog dialog if not already open."""
        try:
            # Check if catalog is already open
            if self._find_catalog_window():
                return True
            
            # Try to open catalog via keyboard shortcut or click
            # Press Ctrl+L for catalog (common shortcut) or click menu
            self.main_window.set_focus()
            time.sleep(0.5)
            
            # Try clicking on "New Catalog & Results" link
            pyautogui.click(pyautogui.locateCenterOnScreen('new_catalog_button.png', confidence=0.8))
            
            time.sleep(1)
            return self._find_catalog_window()
            
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
        """
        try:
            target = self.catalog_window or self.main_window
            target.set_focus()
            
            # Find search box
            search_boxes = target.descendants(control_type="Edit")
            
            for box in search_boxes:
                try:
                    placeholder = box.window_text() or ""
                    if "search" in placeholder.lower() or "part" in placeholder.lower():
                        box.set_focus()
                        box.type_keys("^a")
                        box.type_keys(part_number, with_spaces=True)
                        box.type_keys("{ENTER}")
                        logger.info(f"WORLDPAC: Searching for part {part_number}")
                        time.sleep(2)
                        break
                except:
                    continue
            
            # Extract price from results
            # Look for price patterns in the window
            price = self._extract_price_from_window(target)
            
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
        Looks for patterns like $XX.XX
        """
        try:
            import re
            
            # Get all text elements from window
            texts = []
            for el in window.descendants():
                try:
                    text = el.window_text()
                    if text:
                        texts.append(text)
                except:
                    continue
            
            # Find price patterns
            price_pattern = r'\$(\d+\.?\d*)'
            
            for text in texts:
                matches = re.findall(price_pattern, text)
                for match in matches:
                    try:
                        price = Decimal(match)
                        if price > 0:
                            logger.info(f"WORLDPAC: Found price ${price}")
                            return price
                    except:
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"WORLDPAC: Price extraction failed - {e}")
            return None
    
    async def get_prices(self, part_numbers: List[str]) -> List[Dict]:
        """
        Get prices for multiple part numbers.
        This is the main method called by the scraper service.
        """
        results = []
        
        if not self.is_available():
            logger.error("WORLDPAC: Desktop automation not available")
            return results
        
        if not self.connected:
            if not self.connect():
                logger.error("WORLDPAC: Could not connect to speedDIAL")
                return results
        
        for part_num in part_numbers:
            try:
                result = self.search_part_number(part_num)
                if result:
                    results.append(result)
                else:
                    logger.warning(f"WORLDPAC: No price found for {part_num}")
                
                # Small delay between searches
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"WORLDPAC: Error getting price for {part_num} - {e}")
        
        logger.info(f"WORLDPAC: Found {len(results)} prices out of {len(part_numbers)} parts")
        return results
    
    def click_price_button(self) -> bool:
        """Click the Price button to get pricing."""
        try:
            target = self.catalog_window or self.main_window
            
            # Find and click Price button
            price_btn = target.child_window(title="Price", control_type="Button")
            if price_btn.exists():
                price_btn.click()
                logger.info("WORLDPAC: Clicked Price button")
                time.sleep(2)
                return True
            
            return False
            
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
