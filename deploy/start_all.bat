@echo off
echo ============================================
echo   Estimaro - Start All Services
echo ============================================
echo.

REM Start Chrome Debug Mode
echo [1/3] Starting Chrome in Debug Mode...
start "" "C:\Estimaro\deploy\start_chrome_debug.bat"
timeout /t 5 /nobreak >nul

REM Start Backend
echo [2/3] Starting Backend...
start "" "C:\Estimaro\deploy\start_backend.bat"
timeout /t 3 /nobreak >nul

REM Start Frontend
echo [3/3] Starting Frontend...
start "" "C:\Estimaro\deploy\start_frontend.bat"

echo.
echo ============================================
echo   All Services Started!
echo ============================================
echo.
echo Access your application at:
echo   Frontend: http://localhost/
echo   Backend API: http://localhost:8000/docs
echo.
pause
