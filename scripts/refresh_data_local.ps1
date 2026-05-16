param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

Set-Location $RepoRoot

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$env:PYTHONIOENCODING = "utf-8"

Write-Host "Refreshing cinema data locally from $RepoRoot"
& $python -m src.cinema_agg.build

if ($LASTEXITCODE -ne 0) {
    throw "Aggregator build failed with exit code $LASTEXITCODE"
}

git add -f dist/showtimes.json dist/poster_cache.json

$changes = git diff --cached --name-only
if (-not $changes) {
    Write-Host "No data changes to commit."
    exit 0
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
git commit -m "Update cinema data locally $timestamp"
git push origin $Branch

Write-Host "Local cinema data refreshed and pushed."
