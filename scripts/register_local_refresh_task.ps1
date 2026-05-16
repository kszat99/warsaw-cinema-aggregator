param(
    [string]$TaskName = "Warsaw Cinema Aggregator Local Refresh",
    [string]$DailyAt = "03:00",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$AtLogOn,
    [switch]$Daily
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $RepoRoot "scripts\refresh_data_local.ps1"
if (-not (Test-Path $scriptPath)) {
    throw "Refresh script not found: $scriptPath"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -RepoRoot `"$RepoRoot`""

if (-not $AtLogOn -and -not $Daily) {
    $Daily = $true
}

$triggers = @()
if ($Daily) {
    $triggers += New-ScheduledTaskTrigger -Daily -At $DailyAt
}
if ($AtLogOn) {
    $triggers += New-ScheduledTaskTrigger -AtLogOn
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Builds Warsaw cinema data locally, commits dist/showtimes.json, and pushes it for GitHub Pages deploy." `
    -Force

$triggerDescription = @()
if ($Daily) {
    $triggerDescription += "every day at $DailyAt"
}
if ($AtLogOn) {
    $triggerDescription += "at logon"
}

Write-Host "Registered scheduled task '$TaskName' for $($triggerDescription -join ' and ')."
