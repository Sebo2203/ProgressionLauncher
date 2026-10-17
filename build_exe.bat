@echo off
setlocal
cd /d "%~dp0"

set BUILD_ROOT=.build\ferny_progressor_build
set VENV=%BUILD_ROOT%\.venv
set DIST=dist
set APP_DIR=%CD%

if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
)

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip pyinstaller

if not exist "%DIST%" mkdir "%DIST%"

"%VENV%\Scripts\pyinstaller.exe" ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "ProgressionLauncher-v0.4.4" ^
  --add-data "%APP_DIR%\progression_logo.png;." ^
  --add-data "%APP_DIR%\collection_cache.json;." ^
  --add-data "%APP_DIR%\todds;todds" ^
  --distpath "%DIST%" ^
  --workpath "%BUILD_ROOT%\pyinstaller-work" ^
  --specpath "%BUILD_ROOT%" ^
  progressor.py

echo.
echo Built: %DIST%\ProgressionLauncher-v0.4.4.exe
pause
