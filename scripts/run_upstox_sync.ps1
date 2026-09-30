# run_upstox_sync.ps1
$ErrorActionPreference = "Continue"
$RepoDir = "C:\Work\signaldesk-repo"
$PythonExe = "$RepoDir\.venv\Scripts\python.exe"
$LogFile = "$RepoDir\logs\upstox_sync.log"

New-Item -ItemType Directory -Force -Path "$RepoDir\logs" | Out-Null

function Log($msg) {
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    "$timestamp [UPSTOX-RUNNER] $msg" | Tee-Object -FilePath $LogFile -Append
}

Log "=== Starting Upstox NSE Daily Sync Pipeline ==="

# 1. Check if Docker Desktop engine is running
$dockerRunning = $false
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch { $dockerRunning = $false }

if (-not $dockerRunning) {
    Log "Docker Desktop is not running. Launching Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    
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

# 2. Ensure local-postgres container is running
$pgStatus = docker inspect -f '{{.State.Running}}' "local-postgres" 2>$null
if ($pgStatus -ne "true") {
    Log "Starting container: local-postgres..."
    docker start local-postgres
} else {
    Log "Container local-postgres is already running."
}

# Wait for Postgres port 5432 to actually accept connections
Log "Waiting for PostgreSQL port 5432 to be ready..."
$pgReady = $false
$retries = 0
while ($retries -lt 12) {
    $tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -WarningAction SilentlyContinue
    if ($tcp.TcpTestSucceeded) {
        $pgReady = $true
        Log "PostgreSQL port 5432 is open and accepting connections."
        break
    }
    Start-Sleep -Seconds 2
    $retries++
}

if (-not $pgReady) {
    Log "ERROR: PostgreSQL port 5432 failed to respond within 24 seconds. Aborting sync."
    exit 1
}

# 3. Execute NSE Daily Sync via Python entry point
$BackendDir = "$RepoDir\backend"
Set-Location $BackendDir
$env:PYTHONPATH = "$BackendDir;$RepoDir"

Log "Invoking Upstox Nifty 500 Sync..."
$PyCmd = "import sys; sys.path.insert(0, '$($BackendDir -replace '\\', '/');'); from app.services.seed_nse_data import run_sync; run_sync(mode='nifty500', full_seed_years=2, max_workers=8)"
& $PythonExe -c $PyCmd *>> $LogFile

Log "=== Upstox NSE Pipeline Finished ==="