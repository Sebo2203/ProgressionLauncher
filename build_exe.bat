@echo off
setlocal
cd /d "%~dp0"

set BUILD_ROOT=..\..\work\ferny_progressor_build
set VENV=%BUILD_ROOT%\.venv
set DIST=..\dist
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
  --name "Progression Launcher" ^
  --add-data "%APP_DIR%\progression_logo.png;." ^
  --add-data "%APP_DIR%\collection_cache.json;." ^
  --distpath "%DIST%" ^
  --workpath "%BUILD_ROOT%\pyinstaller-work" ^
  --specpath "%BUILD_ROOT%" ^
  progressor.py

echo.
echo Built: %DIST%\Progression Launcher.exe
pause
