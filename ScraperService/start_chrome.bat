@echo off
echo Starting Google Chrome in Debug Mode...
echo.
echo NOTE: Please close all other Chrome windows before running this,
echo or it might just open a new tab in your existing non-debug Chrome.
echo.
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\selenium\ChromeProfile"
pause
