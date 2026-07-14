param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Branch = "main",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Set-Location $RepoRoot

$stateDir = Join-Path $env:LOCALAPPDATA "WarsawCinemaAggregator"
$lastSuccessPath = Join-Path $stateDir "last_success_date.txt"
$today = Get-Date -Format "yyyy-MM-dd"

if (-not $Force -and (Test-Path $lastSuccessPath)) {
    $lastSuccessDate = (Get-Content $lastSuccessPath -Raw).Trim()
    if ($lastSuccessDate -eq $today) {
        Write-Host "Cinema data was already refreshed successfully today ($today). Use -Force to run again."
        exit 0
    }
}

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($gitCommand) {
    $git = $gitCommand.Source
} else {
    $gitCandidates = @(
        "${env:ProgramFiles}\Git\cmd\git.exe",
        "${env:ProgramFiles}\Git\bin\git.exe",
        "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
        "${env:ProgramFiles(x86)}\Git\bin\git.exe",
        "${env:LOCALAPPDATA}\Programs\Git\cmd\git.exe",
        "${env:LOCALAPPDATA}\Programs\Git\bin\git.exe"
    )
    $git = $gitCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

if (-not $git) {
    throw "Could not find git.exe. Install Git for Windows or add Git to PATH."
}

$env:PYTHONIOENCODING = "utf-8"
$env:MULTIKINO_REQUEST_DELAY_SECONDS = "0"
$env:MULTIKINO_RETRY_DELAYS_SECONDS = "0"

Write-Host "Refreshing cinema data locally from $RepoRoot"
& $python -m src.cinema_agg.build

if ($LASTEXITCODE -ne 0) {
    throw "Aggregator build failed with exit code $LASTEXITCODE"
}

& $git add -f dist/showtimes.json dist/poster_cache.json dist/cinema_health.json

$changes = & $git diff --cached --name-only
if (-not $changes) {
    Write-Host "No data changes to commit."
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    Set-Content -Path $lastSuccessPath -Value $today
    exit 0
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
& $git commit -m "Update cinema data locally $timestamp"
& $git push origin $Branch

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
Set-Content -Path $lastSuccessPath -Value $today

Write-Host "Local cinema data refreshed and pushed."
