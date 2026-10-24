@echo off
title IncuBrix Long-Tail Distribution Service
echo ===================================================
echo   IncuBrix Long-Tail Distribution - Local Launcher
echo ===================================================
echo.

cd /d "%~dp0"

echo [1/3] Checking Docker engine...
docker ps >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] Docker Desktop is running! Starting full microservice stack...
    docker compose up --build -d
    echo.
    echo [SUCCESS] IncuBrix Docker stack started!
    echo Dashboard URL: http://localhost:8000/dashboard
    echo API Docs:      http://localhost:8000/docs
    start http://localhost:8000/dashboard
    goto end
)

echo [INFO] Docker Desktop is not active.
echo [2/3] Launching local FastAPI service via Python venv...
set DATABASE_URL=sqlite+aiosqlite:///./incubrix_local.db
set REDIS_URL=redis://localhost:6379/0
set SIMULATION_MODE=true
set LLM_PROVIDER=gemini

if exist ".\.venv\Scripts\python.exe" (
    echo [3/3] Starting server on http://localhost:8000 ...
    start http://localhost:8000/dashboard
    .\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
) else (
    echo [ERROR] Python virtual environment not found in .venv.
    echo Please run: python -m venv .venv ^&^& .\.venv\Scripts\pip.exe install -r requirements.txt
    pause
)

:end
