@echo off
REM ============================================================
REM  Reddit-Tool Suite - Run the automation in the background
REM  (Optional. Posts due chapters, refreshes stats, checks
REM   for alerts. Needs your Reddit/Patreon keys in .env.)
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\redditsuite.exe" (
  echo Please double-click  setup.bat  first.
  echo.
  pause
  exit /b 1
)

echo.
echo Automation is running. Keep this window open.
echo Close it (or press Ctrl+C) to stop.
echo.

call ".venv\Scripts\redditsuite.exe" run

pause
