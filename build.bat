@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PY=venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] Virtual environment not found at venv\Scripts\python.exe
  echo [INFO] Create it first, then install dependencies.
  exit /b 1
)

echo [INFO] Installing/refreshing dependencies...
"%PY%" -m pip install -r requirements.txt || exit /b 1

echo [INFO] Generating application icon...
"%PY%" src\tools\create_icon.py || (
  echo [ERROR] Failed to run src\tools\create_icon.py
  exit /b 1
)

echo [INFO] Building SmolSTT.exe ...
taskkill /f /im SmolSTT.exe >nul 2>nul
set "PI_TEMP=.pyinstaller_tmp\%RANDOM%%RANDOM%"
set "PI_DIST=.pyinstaller_tmp\%RANDOM%%RANDOM%\dist"
set "PI_WORK=%PI_TEMP%\work"
"%PY%" -m PyInstaller --noconfirm --onefile --windowed --name SmolSTT --paths src --icon src\assets\smolstt.ico --add-data "src\assets\smolstt.ico;assets" --workpath "%PI_WORK%" --specpath "." --distpath "%PI_DIST%" app.py || exit /b 1

if not exist "dist" mkdir dist
copy /y "%PI_DIST%\SmolSTT.exe" "dist\SmolSTT.exe" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Could not write dist\SmolSTT.exe. Close any running SmolSTT process and try again.
  exit /b 1
)

echo [OK] Build complete: dist\SmolSTT.exe
exit /b 0
