# register_scheduled_tasks.ps1
$ErrorActionPreference = "Stop"

$RepoDir = "C:\work\SignalDesk-repo"
$IbkrScript = "$RepoDir\scripts\run_ibkr_sync.ps1"
$UpstoxScript = "$RepoDir\scripts\run_upstox_sync.ps1"

# 1. Define Actions
$IbkrAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$IbkrScript`"" `
    -WorkingDirectory $RepoDir

$UpstoxAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$UpstoxScript`"" `
    -WorkingDirectory $RepoDir

# 2. Define Triggers
$IbkrTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Tuesday, Wednesday, Thursday, Friday, Saturday `
    -At 09:00AM

$UpstoxTrigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At 05:00PM

# 3. Task Settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

# 4. Register IBKR Morning Task
Register-ScheduledTask `
    -TaskName "SignalDesk_IBKR_Morning_Sync" `
    -Action $IbkrAction `
    -Trigger $IbkrTrigger `
    -Settings $Settings `
    -Description "Runs daily S&P 500 and US ETF sync via IBKR at 09:00 IST" `
    -Force

Write-Host "Registered SignalDesk_IBKR_Morning_Sync (Tue-Sat @ 09:00 AM IST)" -ForegroundColor Green

# 5. Register Upstox Evening Task
Register-ScheduledTask `
    -TaskName "SignalDesk_Upstox_Evening_Sync" `
    -Action $UpstoxAction `
    -Trigger $UpstoxTrigger `
    -Settings $Settings `
    -Description "Runs daily EOD delta sync for NSE stocks via Upstox at 17:00 IST" `
    -Force

Write-Host "Registered SignalDesk_Upstox_Evening_Sync (Mon-Fri @ 05:00 PM IST)" -ForegroundColor Green