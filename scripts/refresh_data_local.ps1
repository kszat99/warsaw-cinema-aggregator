param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Branch = "main",
    [switch]$Force,
    [string]$PythonExecutable = "",
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA "WarsawCinemaAggregator")
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $RepoRoot
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

# Shared lock prevents two logon/manual runs from publishing simultaneously.
try {
    $runLock = [IO.File]::Open((Join-Path $StateDir "refresh.lock"), "OpenOrCreate", "ReadWrite", "None")
} catch [IO.IOException] {
    Write-Host "Another local refresh is already running; skipping this invocation."
    exit 0
}

$transcribing = $false
try {
    $logDir = Join-Path $StateDir "logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logPath = Join-Path $logDir ("refresh-{0}-{1}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"), $PID)
    Start-Transcript -Path $logPath | Out-Null
    $transcribing = $true
    Write-Host "Refresh checkout: $RepoRoot"
    Write-Host "Refresh log: $logPath"

    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCommand) {
        $git = $gitCommand.Source
    } else {
        $git = @(
            "${env:ProgramFiles}\Git\cmd\git.exe",
            "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
            "${env:LOCALAPPDATA}\Programs\Git\cmd\git.exe"
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $git) { throw "Could not find git.exe." }

    function Invoke-CheckedGit {
        param([string[]]$GitArgs)
        # Windows PowerShell 5.1 can classify native stderr as an error even
        # when Git succeeds. The native exit code is the success criterion.
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $output = & $git @GitArgs 2>&1
            $code = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($code -ne 0) {
            $output | ForEach-Object { Write-Host ([string]$_) }
            throw "Git $($GitArgs[0]) failed with exit code $code. See the refresh log."
        }
        $output | ForEach-Object { [string]$_ }
    }

    $currentBranch = (Invoke-CheckedGit -GitArgs @("branch", "--show-current") | Out-String).Trim()
    if ($currentBranch -ne $Branch) {
        throw "Refusing to publish from branch '$currentBranch'; this task requires '$Branch'. Use the dedicated live checkout."
    }
    if (Invoke-CheckedGit -GitArgs @("diff", "--cached", "--name-only")) {
        throw "The index contains staged changes. Refusing to include unrelated work in a data commit."
    }
    $dataFiles = @("dist/showtimes.json", "dist/poster_cache.json", "dist/cinema_health.json")
    $otherChanges = @(Invoke-CheckedGit -GitArgs @("diff", "--name-only") | Where-Object { $_ -notin $dataFiles })
    if ($otherChanges.Count) {
        throw "Live source files have uncommitted changes; review them before running the publisher."
    }

    $lastSuccessPath = Join-Path $StateDir "last_success_date.txt"
    $today = Get-Date -Format "yyyy-MM-dd"
    if (-not $Force -and (Test-Path -LiteralPath $lastSuccessPath)) {
        if ((Get-Content -LiteralPath $lastSuccessPath -Raw).Trim() -eq $today) {
            Write-Host "Already refreshed successfully today ($today). Use -Force to run again."
            exit 0
        }
    }

    Invoke-CheckedGit -GitArgs @("fetch", "origin", $Branch) | ForEach-Object { Write-Host $_ }
    Invoke-CheckedGit -GitArgs @("merge", "--ff-only", "origin/$Branch") | ForEach-Object { Write-Host $_ }

    if (-not $PythonExecutable) {
        $PythonExecutable = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    }
    if (-not (Test-Path -LiteralPath $PythonExecutable)) {
        throw "The live checkout needs its own Python environment: $PythonExecutable"
    }

    $env:PYTHONIOENCODING = "utf-8"
    $env:MULTIKINO_REQUEST_DELAY_SECONDS = "0"
    $env:MULTIKINO_RETRY_DELAYS_SECONDS = "0"
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonExecutable -m src.cinema_agg.build 2>&1 | ForEach-Object {
            $safeLine = [regex]::Replace([string]$_, '(?i)(api_key|access_token|token|password)=[^&\s]+', '$1=[REDACTED]')
            Write-Host $safeLine
        }
        $buildExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($buildExitCode -ne 0) {
        throw "Aggregator build failed with exit code $buildExitCode."
    }

    Invoke-CheckedGit -GitArgs (@("add", "-f", "--") + $dataFiles) | ForEach-Object { Write-Host $_ }
    if (Invoke-CheckedGit -GitArgs @("diff", "--cached", "--name-only")) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"
        Invoke-CheckedGit -GitArgs @("commit", "-m", "Update cinema data locally $timestamp") | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "No changed data to commit; checking publication of existing commits."
    }

    # Push even if this run has no new diff: a previous run may have committed
    # successfully but failed to push. Never mark that case as published.
    Invoke-CheckedGit -GitArgs @("push", "origin", "HEAD:refs/heads/$Branch") | ForEach-Object { Write-Host $_ }
    $tempSuccessPath = Join-Path $StateDir "last_success_date.tmp"
    Set-Content -LiteralPath $tempSuccessPath -Value $today
    Move-Item -LiteralPath $tempSuccessPath -Destination $lastSuccessPath -Force
    Write-Host "Local cinema data refreshed and pushed successfully."
} catch {
    Write-Host ("REFRESH FAILED: " + $_.Exception.Message)
    exit 1
} finally {
    if ($transcribing) { Stop-Transcript | Out-Null }
    $runLock.Dispose()
}
