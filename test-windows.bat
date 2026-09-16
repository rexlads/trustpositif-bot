@echo off
REM Double-click to TEST which detection method works from this Indonesian PC.
REM Copy the output and send it back so the checker can be locked in.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1" --test
echo.
pause
