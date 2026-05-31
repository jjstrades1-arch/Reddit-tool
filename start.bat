@echo off
REM ============================================================
REM  Reddit-Tool Suite - Start the dashboard (double-click me)
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\redditsuite.exe" (
  echo It looks like setup hasn't run yet.
  echo Please double-click  setup.bat  first.
  echo.
  pause
  exit /b 1
)

echo.
echo Starting your dashboard...
echo It will open in your web browser at  http://127.0.0.1:8000
echo.
echo Keep this window open while you use it.
echo Close this window (or press Ctrl+C) to stop.
echo.

REM Open the browser a few seconds after the server starts.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"

call ".venv\Scripts\redditsuite.exe" analytics dashboard

pause
