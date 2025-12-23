@echo off
echo ============================================
echo   Estimaro - Frontend Startup
echo ============================================
echo.

cd /d C:\Estimaro\Frontend

echo Starting Estimaro Frontend on port 80...
echo.

REM Serve the built frontend
npx serve -s dist -l 80

pause
