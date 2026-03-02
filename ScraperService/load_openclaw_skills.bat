@echo off
echo ===================================================
echo Estimaro VPS - Loading OpenClaw Agent Skills
echo ===================================================
echo.
echo Placing Estimaro Skills into OpenClaw's central brain...
echo.

:: Get the current folder where this .bat file is located
set "CURRENT_DIR=%~dp0"

:: Ensure the destination skills folder exists
if not exist "%USERPROFILE%\.openclaw\skills\generate_estimate" mkdir "%USERPROFILE%\.openclaw\skills\generate_estimate"

:: Copy our SKILL.md into the central OpenClaw skills directory using relative paths
copy /Y "%CURRENT_DIR%EstimaroSkills\generate_estimate\SKILL.md" "%USERPROFILE%\.openclaw\skills\generate_estimate\SKILL.md" >nul 2>&1

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Failed to copy the skill. Make sure the 'EstimaroSkills' folder is right next to this file.
    pause
    exit /b
)

echo.
echo ===================================================
echo [OK] Skill Copied Successfully!
echo ===================================================
echo.
echo OpenClaw automatically reads skills from the .openclaw folder.
echo You do not need to restart anything!
echo.
echo To test the bot, open your personal WhatsApp and send it a message like:
echo "make estimate for vin 1G0123456789 job Replace brake pads"
echo.
pause
