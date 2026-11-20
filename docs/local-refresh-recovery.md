# Legacy GitHub Pages refresh recovery

The public static site is refreshed by the Windows task `Warsaw Cinema Aggregator Local Refresh`, using the dedicated `main` checkout recorded in `%LOCALAPPDATA%\WarsawCinemaAggregator\live_checkout.txt`. GitHub Actions deploys the committed data; it does not perform the routine daily fetch. This is separate from the VPS application.

On November 17, 19 and 20, 2026, Python DNS lookups failed across cinema sites. The build correctly refused to publish after Multikino returned no screenings. Git connectivity had succeeded, so Git alone was not a sufficient network readiness check. The previous task ran only at logon and had no restart policy; November 18 remained the last published data.

The launcher now checks all configured cinema hostnames using the live Python runtime before fetching or building. It makes up to six attempts, with 15 seconds between attempts. Failure exits without publishing or recording success. Existing build safeguards, publication locking and the once-per-day success marker remain in effect.

Register the task from the dedicated live checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/register_local_refresh_task.ps1 -Daily -DailyAt 08:00 -AtLogOn
```

This enables a daily 08:00 run and a logon run delayed by two minutes. It requires a network connection and retries failed runs up to six times at 15-minute intervals. Runs already successful that day exit without collecting again. The task runs as the interactive user, so the PC must be on and that user logged in; missed daily starts run when available. It does not wake a sleeping PC.

To retry manually, use `Start-ScheduledTask -TaskName 'Warsaw Cinema Aggregator Local Refresh'`. Logs and the last successful publication date are in `%LOCALAPPDATA%\WarsawCinemaAggregator`. A successful local push must still be followed by a successful `Deploy Committed Cinema Data` GitHub Actions run; check the public dataset's `generated_at` timestamp to confirm deployment.

Regression checks: `python -m pytest tests/test_local_refresh.py -q` (Windows PowerShell required). Tests use temporary local repositories and simulated DNS outcomes, including recovery on the second attempt and persistent failure without building or publishing.
