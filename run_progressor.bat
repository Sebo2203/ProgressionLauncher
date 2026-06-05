@echo off
setlocal
cd /d "%~dp0"
python progressor.py
if errorlevel 1 (
  echo.
  echo Progression Launcher failed to start. Make sure Python 3 is installed and available on PATH.
  pause
)
