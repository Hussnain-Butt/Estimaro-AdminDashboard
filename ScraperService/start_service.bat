@echo off
echo ============================================
echo   Estimaro Scraper Service
echo ============================================
echo.

cd /d %~dp0

call venv\Scripts\activate.bat

REM Set API Key (change this for production!)
set SCRAPER_API_KEY=estimaro_scraper_secret_2024

echo Cleaning up Port 5000 if occupied...
powershell -Command "if (Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue) { Stop-Process -Id (Get-NetTCPConnection -LocalPort 5000).OwningProcess -Force }" >nul 2>&1

echo Starting Scraper Service on port 5000...
echo API Key: %SCRAPER_API_KEY:~0,10%...
echo.
echo IMPORTANT: Make sure Chrome is running in debug mode (port 9222)
echo by running start_chrome.bat first!
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 5000

pause
