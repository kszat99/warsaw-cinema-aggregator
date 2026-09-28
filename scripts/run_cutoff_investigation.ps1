param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TargetDate = (Get-Date).AddDays(1).ToString("yyyy-MM-dd"),
    [string]$EarliestStart = "11:00"
)

$ErrorActionPreference = "Stop"

Set-Location $RepoRoot

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$env:PYTHONIOENCODING = "utf-8"
$env:MULTIKINO_REQUEST_DELAY_SECONDS = "0"
$env:MULTIKINO_RETRY_DELAYS_SECONDS = "0"

$outputDir = Join-Path $RepoRoot "outputs\seat-cutoff"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$targetsPath = Join-Path $outputDir "cutoff-targets-$TargetDate.json"
$observationsPath = Join-Path $outputDir "cutoff-observations-$TargetDate.csv"
$logPath = Join-Path $outputDir "cutoff-run-$TargetDate.log"

Start-Transcript -Path $logPath -Append | Out-Null
try {
    Write-Host "Refreshing showtimes before cutoff investigation..."
    & $python -m src.cinema_agg.build
    if ($LASTEXITCODE -ne 0) {
        throw "Aggregator build failed with exit code $LASTEXITCODE"
    }

    Write-Host "Selecting cutoff targets for $TargetDate, earliest screening start $EarliestStart..."
    & $python scripts\select_cutoff_targets.py `
        --showtimes dist\showtimes.json `
        --date $TargetDate `
        --earliest-start $EarliestStart `
        --output $targetsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Cutoff target selection failed with exit code $LASTEXITCODE"
    }

    Write-Host "Running cutoff monitor..."
    & $python scripts\monitor_booking_cutoffs.py `
        --targets $targetsPath `
        --output $observationsPath `
        --interval 60 `
        --after-minutes 45
    if ($LASTEXITCODE -ne 0) {
        throw "Cutoff monitor failed with exit code $LASTEXITCODE"
    }

    Write-Host "Cutoff investigation complete. Output: $observationsPath"
}
finally {
    Stop-Transcript | Out-Null
}
