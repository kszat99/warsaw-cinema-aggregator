$ErrorActionPreference = 'Stop'
Set-Location 'C:\Users\Kacper Szatkowski\PycharmProjects\warsaw-cinema-aggregator'
$env:PYTHONIOENCODING = 'utf-8'
Start-Transcript -Path 'C:\Users\Kacper Szatkowski\PycharmProjects\warsaw-cinema-aggregator\outputs\seat-cutoff\cutoff-run-targeted-2026-09-21.log' -Append | Out-Null
try {
    & 'C:\Users\Kacper Szatkowski\PycharmProjects\warsaw-cinema-aggregator\.venv\Scripts\python.exe' 'C:\Users\Kacper Szatkowski\PycharmProjects\warsaw-cinema-aggregator\scripts\monitor_booking_cutoffs.py' --targets 'C:\Users\Kacper Szatkowski\PycharmProjects\warsaw-cinema-aggregator\outputs\seat-cutoff\cutoff-targets-targeted-2026-09-21.json' --output 'C:\Users\Kacper Szatkowski\PycharmProjects\warsaw-cinema-aggregator\outputs\seat-cutoff\cutoff-observations-targeted-2026-09-21.csv' --interval 60 --after-minutes 45
    if ($LASTEXITCODE -ne 0) { throw "Targeted cutoff monitor failed with exit code $LASTEXITCODE" }
}
finally {
    Stop-Transcript | Out-Null
}
