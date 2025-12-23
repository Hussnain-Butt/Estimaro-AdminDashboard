@echo off
echo ============================================
echo   Estimaro Scraper Service - Setup
echo ============================================
echo.

cd /d %~dp0

REM Create virtual environment
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate and install
call venv\Scripts\activate
echo Installing dependencies...
pip install -r requirements.txt
playwright install chromium

echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo Now run 'start_service.bat' to start the service
pause
