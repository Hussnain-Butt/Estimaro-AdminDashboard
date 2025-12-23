@echo off
echo ============================================
echo   Estimaro - Chrome Debug Mode Startup
echo ============================================
echo.

REM Kill any existing Chrome processes
echo Closing existing Chrome instances...
taskkill /F /IM chrome.exe 2>nul
timeout /t 2 /nobreak >nul

REM Create profile directory if not exists
if not exist "C:\Estimaro\ChromeProfile" mkdir "C:\Estimaro\ChromeProfile"

REM Start Chrome with debugging enabled
echo Starting Chrome in Debug Mode (Port 9222)...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="C:\Estimaro\ChromeProfile" ^
    --disable-background-timer-throttling ^
    --disable-backgrounding-occluded-windows ^
    --disable-renderer-backgrounding ^
    --no-first-run ^
    --restore-last-session

echo.
echo ============================================
echo   Chrome Started Successfully!
echo ============================================
echo.
echo IMPORTANT: Make sure you are logged in to:
echo   1. https://my.alldata.com
echo   2. https://www.partslink24.com
echo   3. https://speeddial.worldpac.com
echo   4. https://shop.ssfautoparts.com
echo.
echo Keep this window MINIMIZED - DO NOT CLOSE!
echo.
pause
