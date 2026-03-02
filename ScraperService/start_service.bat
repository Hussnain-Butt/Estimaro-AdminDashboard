@echo off
echo ============================================
echo   Estimaro Scraper Service
echo ============================================
echo.

cd /d %~dp0
call venv\Scripts\activate

REM Set API Key (change this for production!)
set SCRAPER_API_KEY=estimaro_scraper_secret_2024

echo Cleaning up Port 5000 if occupied (PowerShell Force)...
powershell -Command "Stop-Process -Id (Get-NetTCPConnection -LocalPort 5000).OwningProcess -Force -ErrorAction SilentlyContinue"

echo Starting Scraper Service on port 5000...
echo API Key: %SCRAPER_API_KEY:~0,10%...
echo.
echo Make sure Chrome is running in debug mode (port 9222)
echo.

python main.py

pause
