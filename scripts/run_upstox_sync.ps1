# run_upstox_sync.ps1
$ErrorActionPreference = "Continue"
$RepoDir = "C:\Work\signaldesk-repo"
$PythonExe = "$RepoDir\.venv\Scripts\python.exe"
$LogFile = "$RepoDir\logs\upstox_sync.log"

# Ensure logs directory exists
New-Item -ItemType Directory -Force -Path "$RepoDir\logs" | Out-Null

function Log($msg) {
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$timestamp [UPSTOX-RUNNER] $msg" | Tee-Object -FilePath $LogFile -Append
}

Log "=== Starting Upstox NSE Daily Sync Pipeline ==="

# 1. Ensure local-postgres container is running
$pgStatus = docker inspect -f '{{.State.Running}}' "local-postgres" 2>$null
if ($pgStatus -ne "true") {
    Log "PostgreSQL container is not running. Starting local-postgres..."
    docker start local-postgres
    Start-Sleep -Seconds 5
} else {
    Log "Container local-postgres is already running."
}

# 2. Execute NSE Daily Sync via Python entry point
Log "Invoking NSE sync via seed_nse_data..."

# Set working directory to backend so 'app' imports resolve cleanly
$BackendDir = "$RepoDir\backend"
Set-Location $BackendDir
$env:PYTHONPATH = "$BackendDir;$RepoDir"

# Run Upstox Sync
Log "Invoking Upstox Sync..."
$PyCmd = "import sys; sys.path.insert(0, '$($BackendDir -replace '\\', '/');'); from app.services.seed_nse_data import run_full_universe_sync; run_full_universe_sync(full_seed_years=2, max_workers=8)"
& $PythonExe -c $PyCmd *>> $LogFile

Log "=== Upstox NSE Pipeline Finished ==="
