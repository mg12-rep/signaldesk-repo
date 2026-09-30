# run_ibkr_sync.ps1
$ErrorActionPreference = "Continue"
$RepoDir = "C:\Work\signaldesk-repo"
$PythonExe = "$RepoDir\.venv\Scripts\python.exe"
$LogFile = "$RepoDir\logs\ibkr_sync.log"

# Ensure logs directory exists
New-Item -ItemType Directory -Force -Path "$RepoDir\logs" | Out-Null

function Log($msg) {
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$timestamp [IBKR-RUNNER] $msg" | Tee-Object -FilePath $LogFile -Append
}

Log "=== Starting IBKR Morning Sync Pipeline ==="

# 1. Check if Docker Desktop engine is running
$dockerRunning = $false
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch { $dockerRunning = $false }

if (-not $dockerRunning) {
    Log "Docker Desktop is not running. Launching Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    
    # Wait up to 90s for Docker daemon to become responsive
    $retries = 0
    while ($retries -lt 18) {
        Start-Sleep -Seconds 5
        try {
            $null = docker info 2>&1
            if ($LASTEXITCODE -eq 0) {
                $dockerRunning = $true
                Log "Docker daemon is ready."
                break
            }
        } catch {}
        $retries++
    }
    if (-not $dockerRunning) {
        Log "ERROR: Timed out waiting for Docker to start. Aborting sync."
        exit 1
    }
}

# 2. Ensure Postgres and IB Gateway containers are running
$containers = @("local-postgres", "local-ibgateway")
foreach ($c in $containers) {
    $status = docker inspect -f '{{.State.Running}}' $c 2>$null
    if ($status -ne "true") {
        Log "Starting container: $c"
        docker start $c
    } else {
        Log "Container $c is already running."
    }
}

# Allow Gateway socket to stabilize
Start-Sleep -Seconds 5

# 3. Step A: Execute S&P 500 Daily Sync
# Set working directory to backend so 'app' imports resolve
$BackendDir = "$RepoDir\backend"
Set-Location $BackendDir
$env:PYTHONPATH = "$BackendDir;$RepoDir"

# Step A: Execute S&P 500 Daily Sync
Log "Step A: Invoking seed_us_universe_from_db (S&P 500)..."
& $PythonExe -c "import sys; sys.path.insert(0, r'$BackendDir'); from app.services.seed_us_data import seed_us_universe_from_db; seed_us_universe_from_db()" *>> $LogFile

# Step B: Execute US ETF Daily Sync
Log "Step B: Invoking run_us_etf_sync_standalone (US ETFs)..."
& $PythonExe -c "import sys; sys.path.insert(0, r'$BackendDir'); from app.services.seed_us_data import run_us_etf_sync_standalone; run_us_etf_sync_standalone()" *>> $LogFile