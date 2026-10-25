# ============================================================
# IncuBrix — Local Dev Startup Script (no Docker needed)
# Usage: .\run_local_dev.ps1
# ============================================================

Write-Host "IncuBrix Local Dev Server Starting..." -ForegroundColor Cyan

# Load .env.local overrides into current process environment
if (Test-Path ".env.local") {
    Get-Content ".env.local" | Where-Object { $_ -notmatch "^\s*#" -and $_ -match "=" } | ForEach-Object {
        $parts = $_ -split "=", 2
        $key = $parts[0].Trim()
        $val = if ($parts.Length -gt 1) { $parts[1].Trim() } else { "" }
        [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
    Write-Host "Loaded .env.local (SQLite, no Docker required)" -ForegroundColor Green
} else {
    Write-Host "WARNING: .env.local not found, using .env defaults" -ForegroundColor Yellow
}

# Ensure outputs directory exists
New-Item -ItemType Directory -Force -Path ".\outputs\mrss" | Out-Null

# Show active config
Write-Host ""
Write-Host "Database : $($env:DATABASE_URL)" -ForegroundColor DarkCyan
Write-Host "Simulation: $($env:SIMULATION_MODE)" -ForegroundColor DarkCyan
Write-Host "Port     : 8000" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "Dashboard -> http://localhost:8000/dashboard" -ForegroundColor Yellow
Write-Host "API Docs  -> http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "Health    -> http://localhost:8000/health" -ForegroundColor Yellow
Write-Host ""

# Start uvicorn with hot-reload
.\.venv\Scripts\uvicorn.exe api.main:app --host 0.0.0.0 --port 8000 --reload
