@echo off
REM Launch Chrome in debug mode so Playwright can connect to existing logged-in sessions
REM IMPORTANT: Close ALL Chrome windows before running this, otherwise debug mode wont activate

set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
set USER_DATA="C:\ChromeDebugProfile"
set PORT=9222

if not exist %CHROME_PATH% (
    set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

echo Launching Chrome with remote debugging on port %PORT%
echo Profile: %USER_DATA%
echo.
echo NOTE: First time, login to ALLDATA, PartsLink24, SSF, WorldPac in this Chrome.
echo       Sessions will persist in the profile folder.
echo.

start "" %CHROME_PATH% --remote-debugging-port=%PORT% --user-data-dir=%USER_DATA%
