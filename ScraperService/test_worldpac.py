"""
WORLDPAC COMPLETE TEST - Efficient Error Detection
===================================================
Tests the entire Worldpac flow with detailed error reporting.

Usage: python test_worldpac.py [VIN] [JOB]
Example: python test_worldpac.py WBA3B1C59FK456789 "Engine Oil Leak"
"""

import sys
import time
import traceback
from datetime import datetime
import pyautogui
from pywinauto import Application

# ============================================================
# CONFIGURATION - Manually captured positions
# ============================================================
CONFIG = {
    # VIN field (relative to catalog window)
    "vin_field_rel": (467, 73),
    "vin_search_rel": (528, 71),
    
    # Vehicle selection (absolute - popup position)
    "vehicle_row_abs": (632, 276),
    
    # LEFT PANEL - Category Tree (relative to catalog)
    # Categories like "Replacement Parts", "Brake", etc.
    "category_replacement_parts_rel": (120, 230),  # "Replacement Parts" in tree
    "category_brake_rel": (120, 310),              # "Brake" subcategory
    "category_cooling_rel": (120, 370),            # "Cooling System"
    "category_engine_rel": (120, 450),             # "Engine Electrical"
    
    # RIGHT PANEL - Parts list (relative to catalog)
    "parts_first_row_rel": (750, 220),             # First part in right panel
    "parts_checkbox_rel": (880, 273),              # Checkbox - USER CAPTURED!
    
    # Price button (relative to catalog - bottom right)
    "price_button_rel": (1098, 641),               # Price button - USER CAPTURED!
    
    # OLD - keeping for reference
    # "category_search_rel": (150, 130),
    # "search_result_rel": (400, 160),
    # "checkbox_abs": (942, 601),
    # "price_button_abs": (1233, 752),
}

# Default test data
DEFAULT_VIN = "WBA3B1C59FK456789"
DEFAULT_JOB = "Engine Oil Leak"


class WorldpacTester:
    def __init__(self, vin: str, job: str):
        self.vin = vin
        self.job = job
        self.app = None
        self.catalog = None
        self.win_left = 0
        self.win_top = 0
        self.errors = []
        self.step_results = []
        
    def log(self, message: str, level: str = "INFO"):
        """Print log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        symbol = {"INFO": "ℹ️", "OK": "✅", "ERROR": "❌", "WARN": "⚠️"}.get(level, "")
        print(f"[{timestamp}] {symbol} {message}")
        
    def screenshot(self, name: str):
        """Take and save screenshot."""
        filename = f"worldpac_{name}.png"
        pyautogui.screenshot().save(filename)
        self.log(f"Screenshot: {filename}", "INFO")
        return filename
        
    def add_result(self, step: str, success: bool, message: str = ""):
        """Record step result."""
        self.step_results.append({
            "step": step,
            "success": success,
            "message": message
        })
        if not success:
            self.errors.append(f"{step}: {message}")
            
    # ============================================================
    # STEP 1: Connect to Worldpac
    # ============================================================
    def step1_connect(self) -> bool:
        """Connect to Worldpac speedDIAL application."""
        self.log("STEP 1: Connecting to Worldpac speedDIAL...")
        
        try:
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
                # Try direct window search
                try:
                    self.catalog = self.app.window(title_re=".*Catalog.*")
                except:
                    self.catalog = main_win
                    
            # Get window position
            rect = self.catalog.rectangle()
            self.win_left = rect.left
            self.win_top = rect.top
            
            self.log(f"Connected! Window at ({self.win_left}, {self.win_top})", "OK")
            self.log(f"Window size: {rect.width()}x{rect.height()}", "INFO")
            
            # Focus the window
            self.catalog.set_focus()
            time.sleep(0.5)
            
            self.add_result("Connect", True)
            self.screenshot("01_connected")
            return True
            
        except Exception as e:
            self.log(f"Connection failed: {e}", "ERROR")
            self.add_result("Connect", False, str(e))
            return False
            
    # ============================================================
    # STEP 2: Enter VIN
    # ============================================================
    def step2_enter_vin(self) -> bool:
        """Enter VIN in the VIN field."""
        self.log(f"STEP 2: Entering VIN: {self.vin}...")
        
        try:
            # Calculate VIN field position
            vin_x = self.win_left + CONFIG["vin_field_rel"][0]
            vin_y = self.win_top + CONFIG["vin_field_rel"][1]
            
            self.log(f"Clicking VIN field at ({vin_x}, {vin_y})", "INFO")
            
            # Click VIN field
            pyautogui.click(vin_x, vin_y)
            time.sleep(0.3)
            
            # Clear and type VIN
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('delete')
            time.sleep(0.1)
            
            pyautogui.typewrite(self.vin, interval=0.05)
            time.sleep(0.5)
            
            self.screenshot("02_vin_entered")
            
            # Click search button
            search_x = self.win_left + CONFIG["vin_search_rel"][0]
            search_y = self.win_top + CONFIG["vin_search_rel"][1]
            
            self.log(f"Clicking search at ({search_x}, {search_y})", "INFO")
            pyautogui.click(search_x, search_y)
            time.sleep(4)  # Wait for VIN lookup
            
            self.screenshot("03_after_vin_search")
            self.log("VIN entered and searched", "OK")
            self.add_result("VIN Entry", True)
            return True
            
        except Exception as e:
            self.log(f"VIN entry failed: {e}", "ERROR")
            self.log(traceback.format_exc(), "ERROR")
            self.add_result("VIN Entry", False, str(e))
            return False
            
    # ============================================================
    # STEP 3: Select Vehicle
    # ============================================================
    def step3_select_vehicle(self) -> bool:
        """Select vehicle from popup (if appears) or verify auto-select."""
        self.log("STEP 3: Selecting vehicle...")
        
        try:
            # Double-click on vehicle row (handles popup case)
            vehicle_x, vehicle_y = CONFIG["vehicle_row_abs"]
            
            self.log(f"Double-clicking vehicle at ({vehicle_x}, {vehicle_y})", "INFO")
            pyautogui.doubleClick(vehicle_x, vehicle_y)
            time.sleep(2)
            
            self.screenshot("04_vehicle_selected")
            
            # Verify by checking if Year/Make/Model are filled
            # (We'll rely on the screenshot for now)
            
            self.log("Vehicle selection attempted", "OK")
            self.add_result("Vehicle Select", True)
            return True
            
        except Exception as e:
            self.log(f"Vehicle selection failed: {e}", "ERROR")
            self.add_result("Vehicle Select", False, str(e))
            return False
            
    # ============================================================
    # STEP 4: Search Job Description in Category
    # ============================================================
    def step4_search_job(self) -> bool:
        """Search for job description in category search field."""
        self.log(f"STEP 4: Searching for job: {self.job}...")
        
        try:
            # Update window position
            rect = self.catalog.rectangle()
            self.win_left = rect.left
            self.win_top = rect.top
            
            # Category search field is at top-left of Category panel
            # Based on screenshot: "Search part type name... Ex. brake"
            search_x = self.win_left + 150  # Left panel search field
            search_y = self.win_top + 180   # Below "Category" header
            
            self.log(f"Clicking category search at ({search_x}, {search_y})", "INFO")
            pyautogui.click(search_x, search_y)
            time.sleep(0.3)
            
            # Clear and type job description
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('delete')
            time.sleep(0.1)
            
            # Type job description
            pyautogui.typewrite(self.job, interval=0.03)
            time.sleep(1)
            pyautogui.press('enter')
            time.sleep(2)  # Wait for results
            
            self.screenshot("05_job_searched")
            self.log(f"Job '{self.job}' searched", "OK")
            self.add_result("Search Job", True)
            return True
            
        except Exception as e:
            self.log(f"Job search failed: {e}", "ERROR")
            self.add_result("Search Job", False, str(e))
            return False
            
    # ============================================================
    # STEP 5: Click on Search Result/Category
    # ============================================================
    def step5_click_result(self) -> bool:
        """Click on the search result or matching category."""
        self.log("STEP 5: Clicking search result...")
        
        try:
            # Click on first result in category tree (should be highlighted)
            # First item in left panel after search
            result_x = self.win_left + 150
            result_y = self.win_top + 230  # First result row
            
            self.log(f"Clicking result at ({result_x}, {result_y})", "INFO")
            pyautogui.click(result_x, result_y)
            time.sleep(2)  # Wait for parts to load
            
            self.screenshot("06_result_clicked")
            self.log("Search result clicked, parts loading in right panel", "OK")
            self.add_result("Click Result", True)
            return True
            
        except Exception as e:
            self.log(f"Result click failed: {e}", "ERROR")
            self.add_result("Click Result", False, str(e))
            return False
            
    # ============================================================
    # STEP 6: Select ALL Parts in RIGHT Panel
    # ============================================================
    def step6_select_all_parts(self) -> bool:
        """Select ALL parts/checkboxes in the RIGHT panel."""
        self.log("STEP 6: Selecting ALL parts in RIGHT panel...")
        
        try:
            # Checkbox column X position (relative to catalog)
            checkbox_x = self.win_left + CONFIG["parts_checkbox_rel"][0]
            
            # Start Y position and spacing between rows
            start_y = self.win_top + 210  # First checkbox row
            row_spacing = 25               # Approx spacing between checkboxes
            max_rows = 15                  # Max visible rows
            
            parts_selected = 0
            
            # Click all visible checkboxes
            for i in range(max_rows):
                checkbox_y = start_y + (i * row_spacing)
                
                # Don't click below the window
                if checkbox_y > self.win_top + 550:
                    break
                    
                pyautogui.click(checkbox_x, checkbox_y)
                time.sleep(0.1)
                parts_selected += 1
            
            self.log(f"Clicked {parts_selected} checkboxes", "INFO")
            
            # Scroll down and click more if needed
            pyautogui.scroll(-5)  # Scroll down
            time.sleep(0.5)
            
            for i in range(5):  # Click a few more after scroll
                checkbox_y = start_y + (i * row_spacing)
                pyautogui.click(checkbox_x, checkbox_y)
                time.sleep(0.1)
                parts_selected += 1
            
            self.screenshot("07_parts_selected")
            self.log(f"Selected ~{parts_selected} parts", "OK")
            self.add_result("Select Parts", True, f"Selected ~{parts_selected} parts")
            return True
            
        except Exception as e:
            self.log(f"Part selection failed: {e}", "ERROR")
            self.add_result("Select Parts", False, str(e))
            return False
            
    # ============================================================
    # STEP 7: Click Price Button
    # ============================================================
    def step7_click_price(self) -> bool:
        """Click the Price button at bottom right."""
        self.log("STEP 7: Clicking Price button...")
        
        try:
            # Price button at bottom right of catalog window
            price_x = self.win_left + CONFIG["price_button_rel"][0]
            price_y = self.win_top + CONFIG["price_button_rel"][1]
            
            self.log(f"Clicking Price at ({price_x}, {price_y})", "INFO")
            pyautogui.click(price_x, price_y)
            time.sleep(3)
            
            self.screenshot("08_price_clicked")
            self.log("Price button clicked", "OK")
            self.add_result("Click Price", True)
            return True
            
        except Exception as e:
            self.log(f"Price click failed: {e}", "ERROR")
            self.add_result("Click Price", False, str(e))
            return False
            
    # ============================================================
    # STEP 8: Extract ALL Prices using OCR with Scrolling
    # ============================================================
    def step8_extract_prices(self) -> bool:
        """Extract ALL prices from Price view using OCR with scrolling."""
        self.log("STEP 8: Extracting ALL prices using OCR...")
        
        try:
            import re
            from PIL import Image
            import pytesseract
            
            # Wait for Price & Availability view to fully load
            time.sleep(2)
            
            all_prices = []
            scroll_count = 0
            max_scrolls = 5  # Max pages to scroll
            
            while scroll_count < max_scrolls:
                # Take screenshot
                screenshot = pyautogui.screenshot()
                filename = f"worldpac_price_page_{scroll_count + 1}.png"
                screenshot.save(filename)
                self.log(f"Screenshot {scroll_count + 1}: {filename}", "INFO")
                
                # OCR extraction
                self.log("Running OCR...", "INFO")
                text = pytesseract.image_to_string(screenshot)
                
                # Find price patterns ($XX.XX format)
                price_pattern = r'\$(\d+\.\d{2})'
                matches = re.findall(price_pattern, text)
                
                new_prices = 0
                for m in matches:
                    try:
                        price = float(m)
                        if 1.0 <= price <= 1000:  # Reasonable range
                            if price not in all_prices:
                                all_prices.append(price)
                                new_prices += 1
                    except:
                        pass
                
                self.log(f"  Found {new_prices} new prices (Total: {len(all_prices)})", "INFO")
                
                # If no new prices found, we've reached the end
                if new_prices == 0 and scroll_count > 0:
                    self.log("No new prices found, stopping scroll", "INFO")
                    break
                
                # Scroll down for more prices
                pyautogui.scroll(-5)  # Scroll down
                time.sleep(1)
                scroll_count += 1
            
            self.screenshot("09_final_prices")
            
            if all_prices:
                self.log(f"✅ EXTRACTED {len(all_prices)} total prices!", "OK")
                self.log(f"Prices: {all_prices[:10]}{'...' if len(all_prices) > 10 else ''}", "INFO")
                self.add_result("Extract Prices", True, f"OCR extracted {len(all_prices)} prices")
                return True
            else:
                self.log("⚠️ No prices extracted via OCR", "WARN")
                self.add_result("Extract Prices", False, "OCR extraction failed")
                return False
                
        except Exception as e:
            self.log(f"Price extraction failed: {e}", "ERROR")
            self.add_result("Extract Prices", False, str(e))
            return False
            
    # ============================================================
    # RUN ALL TESTS
    # ============================================================
    def run(self):
        """Run all test steps."""
        print("\n" + "=" * 60)
        print("WORLDPAC COMPLETE TEST")
        print("=" * 60)
        print(f"VIN: {self.vin}")
        print(f"JOB: {self.job}")
        print("=" * 60 + "\n")
        
        steps = [
            ("Connect", self.step1_connect),
            ("VIN Entry", self.step2_enter_vin),
            ("Vehicle Select", self.step3_select_vehicle),
            ("Search Job", self.step4_search_job),
            ("Click Result", self.step5_click_result),
            ("Select Parts", self.step6_select_all_parts),
            ("Click Price", self.step7_click_price),
            ("Extract Prices", self.step8_extract_prices),
        ]
        
        for name, step_func in steps:
            print(f"\n{'─' * 40}")
            if not step_func():
                self.log(f"Stopping at step: {name}", "ERROR")
                break
                
        # Print summary
        self.print_summary()
        
    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for r in self.step_results if r["success"])
        total = len(self.step_results)
        
        for r in self.step_results:
            status = "✅ PASS" if r["success"] else "❌ FAIL"
            msg = f" - {r['message']}" if r["message"] else ""
            print(f"  {status} | {r['step']}{msg}")
            
        print("─" * 60)
        print(f"  Result: {passed}/{total} steps passed")
        
        if self.errors:
            print("\n⚠️  ERRORS:")
            for err in self.errors:
                print(f"    • {err}")
                
        print("\n📸 Check screenshots:")
        print("    worldpac_01_connected.png")
        print("    worldpac_02_vin_entered.png")
        print("    worldpac_03_after_vin_search.png")
        print("    worldpac_04_vehicle_selected.png")
        print("    worldpac_05_category_searched.png")
        print("    worldpac_06_result_clicked.png")
        print("    worldpac_07_checkbox_clicked.png")
        print("    worldpac_08_price_clicked.png")
        print("    worldpac_09_final_state.png")
        print("=" * 60)


def main():
    """Main entry point."""
    # Parse arguments
    vin = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIN
    job = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_JOB
    
    # Run test
    tester = WorldpacTester(vin, job)
    tester.run()


if __name__ == "__main__":
    main()
