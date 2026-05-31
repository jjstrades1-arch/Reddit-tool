@echo off
REM ============================================================
REM  Reddit-Tool Suite - First-time setup (double-click me once)
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo    Reddit-Tool Suite - First-time setup
echo ============================================
echo.

REM --- Check that Python is installed ---
python --version >nul 2>&1
if errorlevel 1 (
  echo [X] Python is not installed.
  echo.
  echo     1. Download it from:  https://www.python.org/downloads/
  echo     2. Run the installer.
  echo     3. IMPORTANT: tick the box "Add Python to PATH".
  echo     4. Then double-click setup.bat again.
  echo.
  pause
  exit /b 1
)

echo [1/4] Creating a private space for the app...
python -m venv .venv
if errorlevel 1 ( echo Could not create environment. & pause & exit /b 1 )

echo [2/4] Installing the app (this may take a few minutes)...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 ( echo Install failed. & pause & exit /b 1 )

echo [3/4] Creating your settings file...
if not exist ".env" copy ".env.example" ".env" >nul

echo [4/4] Building the database...
call ".venv\Scripts\redditsuite.exe" db init

echo.
echo ============================================
echo    All done!
echo.
echo    Next:
echo      - To add your Reddit/Patreon keys later,
echo        open the file named ".env" in Notepad.
echo        (You can skip this to just try it out.)
echo      - Double-click  start.bat  to launch.
echo ============================================
echo.
pause
