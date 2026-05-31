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

REM --- Guard: are we running from INSIDE the ZIP / a Temp folder? ---
echo %CD% | find /I "\Temp\" >nul
if not errorlevel 1 goto :inzip
echo %CD% | find /I ".zip" >nul
if not errorlevel 1 goto :inzip

REM --- Find Python (try "python", then the "py" launcher) ---
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY py --version >nul 2>&1 && set "PY=py"
if not defined PY goto :nopython

echo [1/4] Creating a private space for the app...
%PY% -m venv .venv
if errorlevel 1 (
  echo     First attempt failed - trying an alternate method...
  rmdir /s /q .venv 2>nul
  %PY% -m venv .venv --without-pip
  if errorlevel 1 goto :novenv
)

REM --- Make sure the installer (pip) exists inside the private space ---
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo     Setting up the installer...
  ".venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1
)
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo     Downloading the installer...
  powershell -NoProfile -Command "try { Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile get-pip.py } catch { exit 1 }"
  ".venv\Scripts\python.exe" get-pip.py
  del get-pip.py >nul 2>&1
)

echo [2/4] Installing the app (this may take a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :installfail

echo [3/4] Creating your settings file...
if not exist ".env" copy ".env.example" ".env" >nul

echo [4/4] Building the database...
".venv\Scripts\redditsuite.exe" db init

echo.
echo ============================================
echo    All done!
echo      - Double-click  start.bat  to launch.
echo      - To add Reddit/Patreon keys later, open
echo        the file ".env" in Notepad.
echo ============================================
echo.
pause
exit /b 0

:inzip
echo [X] It looks like you're running this from INSIDE the ZIP file.
echo.
echo     Please extract it first:
echo       1. Open your Downloads folder.
echo       2. RIGHT-CLICK the Reddit-tool ZIP file.
echo       3. Choose "Extract All..."  then  "Extract".
echo       4. Open the new folder that appears.
echo       5. Double-click setup.bat from THERE.
echo.
pause
exit /b 1

:nopython
echo [X] Python is not installed.
echo.
echo     1. Go to:  https://www.python.org/downloads/
echo     2. Run the installer.
echo     3. IMPORTANT: tick the box "Add Python to PATH".
echo     4. Then double-click setup.bat again.
echo.
pause
exit /b 1

:novenv
echo [X] Could not create the private environment.
echo     Try reinstalling Python from https://www.python.org/downloads/
echo     and be sure to tick "Add Python to PATH".
echo.
pause
exit /b 1

:installfail
echo [X] The install step failed. Please check your internet connection
echo     and run setup.bat again.
echo.
pause
exit /b 1
