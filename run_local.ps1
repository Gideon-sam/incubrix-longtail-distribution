# IncuBrix Long-Tail Distribution - PowerShell Local Launcher
Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  IncuBrix Long-Tail Distribution - Local Launcher" -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

Set-Location -Path $PSScriptRoot

# 1. Test if Docker Desktop is available
$dockerRunning = $false
try {
    $null = docker ps 2>$null
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch {}

if ($dockerRunning) {
    Write-Host "[INFO] Docker Desktop is active! Starting microservice stack..." -ForegroundColor Green
    docker compose up --build -d
    Start-Process "http://localhost:8000/dashboard"
    Write-Host "[SUCCESS] Running at http://localhost:8000/dashboard" -ForegroundColor Green
    exit 0
}

# 2. Fallback to direct Python service
Write-Host "[INFO] Docker not detected. Starting direct Python FastAPI server..." -ForegroundColor Yellow
$env:DATABASE_URL = "sqlite+aiosqlite:///./incubrix_local.db"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:SIMULATION_MODE = "true"
$env:LLM_PROVIDER = "gemini"

if (Test-Path ".\.venv\Scripts\python.exe") {
    Start-Process "http://localhost:8000/dashboard"
    & ".\.venv\Scripts\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
} else {
    Write-Host "[ERROR] .venv not found. Please create virtual environment." -ForegroundColor Red
}
