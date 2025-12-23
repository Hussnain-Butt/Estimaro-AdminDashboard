@echo off
echo ============================================
echo   Estimaro - Backend Startup
echo ============================================
echo.

cd /d C:\Estimaro\Backend

REM Activate virtual environment
call venv\Scripts\activate

REM Set production environment
set DEBUG=False
set PYTHONUNBUFFERED=1

echo Starting Estimaro Backend on port 8000...
echo.

REM Start with Uvicorn
python run_backend.py

pause
