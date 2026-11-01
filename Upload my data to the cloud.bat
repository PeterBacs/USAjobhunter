@echo off
title USA Job Hunter - upload data to the cloud
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run "Start USA Job Hunter.bat" once first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q "psycopg[binary]>=3.2" >nul 2>&1
".venv\Scripts\python.exe" backend\upload_data.py
echo.
pause
