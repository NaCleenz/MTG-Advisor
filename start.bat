@echo off
setlocal

set PORT=8000
set BACKEND=%~dp0backend
set ENV_FILE=%~dp0.env

:: ── Load .env if it exists ────────────────────────────────────────────────
if exist "%ENV_FILE%" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%ENV_FILE%") do (
        if not "%%a"=="" if not "%%a:~0,1%"=="#" set "%%a=%%b"
    )
)

:: ── Check Python ─────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

:: ── Warn if no Groq key ───────────────────────────────────────────────────
if "%GROQ_API_KEY%"=="" (
    echo WARNING: GROQ_API_KEY not set. AI features will use basic keyword matching.
    echo Copy .env.example to .env and add your free key from https://console.groq.com
    echo.
)

:: ── Kill any previous instance on port 8000 ──────────────────────────────
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    echo Stopping previous instance (PID %%a)...
    taskkill /PID %%a /F >nul 2>&1
)

:: ── Install / verify dependencies ────────────────────────────────────────
echo Checking dependencies...
python -m pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    python -m pip install -r "%BACKEND%\requirements.txt" --quiet
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
)

:: ── Start the backend ─────────────────────────────────────────────────────
echo Starting Commander Advisor...
start "MTG Advisor Backend" /min cmd /c "cd /d "%BACKEND%" && python app.py"

:: ── Wait for server to be ready ───────────────────────────────────────────
echo Waiting for server...
:WAIT_LOOP
timeout /t 1 /nobreak >nul
curl -s http://127.0.0.1:%PORT%/api/health >nul 2>&1
if errorlevel 1 goto WAIT_LOOP

:: ── Open browser ──────────────────────────────────────────────────────────
start "" "http://127.0.0.1:%PORT%"

echo Commander Advisor is running at http://127.0.0.1:%PORT%
echo Close this window to stop the server.
echo.
pause
