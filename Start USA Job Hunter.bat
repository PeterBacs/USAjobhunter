@echo off
title USA JOB HUNTER
cd /d "%~dp0"

REM If the app is already running, just open the browser.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
    echo USA JOB HUNTER is already running. Opening the browser...
    start "" http://127.0.0.1:8000
    timeout /t 3 >nul
    exit /b
)

REM First run: create the Python environment and install dependencies.
if not exist ".venv\Scripts\python.exe" (
    echo Setting up for the first time. This takes a few minutes...
    python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Installing dependencies failed. & pause & exit /b 1)
)

echo.
echo  ==============================================
echo    USA JOB HUNTER is starting...
echo    Open: http://127.0.0.1:8000
echo    Keep this window open while you use the app.
echo    Close this window (or press Ctrl+C) to stop.
echo  ==============================================
echo.

REM Open the browser a few seconds after the server starts.
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:8000'"

".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

echo.
echo USA JOB HUNTER has stopped.
pause
