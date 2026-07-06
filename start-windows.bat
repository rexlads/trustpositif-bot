@echo off
REM Double-click this on the Indonesian Windows RDP to run the real-time bot.
REM First time only: it installs the two Python packages it needs.
cd /d "%~dp0"
echo Installing dependencies (first run only)...
pip install -r requirements.txt python-dotenv
echo.
echo Starting TrustPositif real-time runner. Close this window to stop.
python run_local.py
pause
