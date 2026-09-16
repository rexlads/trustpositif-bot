@echo off
REM Double-click this on the Indonesian Windows RDP to run the real-time bot.
cd /d "%~dp0"

REM Install Python automatically if it's not there yet (Windows 10/11 winget).
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Installing via winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo If install just finished, CLOSE this window and double-click again.
  pause
  exit /b
)

echo Installing dependencies (first run only)...
python -m pip install --quiet -r requirements.txt python-dotenv

echo.
echo Starting TrustPositif real-time runner. Close this window to stop.
python run_local.py
pause
