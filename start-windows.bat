@echo off
REM Double-click to run the TrustPositif real-time bot on Windows (no Python).
REM Uses built-in PowerShell. Make sure .env is filled in first.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1"
echo.
echo (Jendela berhenti. Tekan tombol apa saja untuk menutup.)
pause
