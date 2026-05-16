param(
    [string]$TaskName = "Warsaw Cinema Aggregator Local Refresh",
    [string]$DailyAt = "03:00",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $RepoRoot "scripts\refresh_data_local.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "Refresh script not found: $scriptPath"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -RepoRoot `"$RepoRoot`""

$trigger = New-ScheduledTaskTrigger -Daily -At $DailyAt
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Builds Warsaw cinema data locally, commits dist/showtimes.json, and pushes it for GitHub Pages deploy." `
    -Force

Write-Host "Registered scheduled task '$TaskName' for every day at $DailyAt."
