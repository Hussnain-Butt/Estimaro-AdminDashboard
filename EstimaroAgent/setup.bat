@echo off
REM Run this ONCE on the VPS to setup the agent environment
echo === Estimaro Agent Setup ===

echo.
echo [1/5] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11 from python.org and check "Add to PATH"
    pause
    exit /b 1
)

echo.
echo [2/5] Creating virtual environment...
python -m venv venv
call venv\Scripts\activate.bat

echo.
echo [3/5] Installing Python packages...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo [4/5] Installing Playwright Chromium...
playwright install chromium

echo.
echo [5/5] Verifying Ollama + Hermes...
ollama list | findstr hermes3
if errorlevel 1 (
    echo WARNING: hermes3:8b not pulled yet. Run: ollama pull hermes3:8b
)

echo.
echo === Setup complete ===
echo.
echo Next steps:
echo   1. Copy .env.example to .env and fill in your keys
echo   2. Run: start_chrome_debug.bat (to launch logged-in Chrome)
echo   3. Run: venv\Scripts\activate ^&^& python test_hermes.py
echo.
pause
