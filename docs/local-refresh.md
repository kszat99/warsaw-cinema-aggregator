# Local production refresh

The live scheduled job must use a dedicated checkout of `main`, with its own `.venv`. Do not point it at the development folder or switch its branch. Keep this checkout while the task uses it.

The development checkout can use `codex/server-app` independently. Neither its uncommitted edits nor its Python dependency changes should enter the daily publisher.

When Windows denies permission to edit an existing task definition, the compatible launcher reads `%LOCALAPPDATA%\WarsawCinemaAggregator\live_checkout.txt` and delegates to the checkout recorded there. Keep this launcher behavior in the development branch. A future administrator can point the task directly at the live script; application code and dependencies already run from the live checkout either way.

`scripts/refresh_data_local.ps1` saves transcripts under `%LOCALAPPDATA%\WarsawCinemaAggregator\logs`, prevents overlapping invocations, verifies the branch and refuses staged/uncommitted source changes. Only the three generated `dist/` data files are committed. Native command exit codes determine failure; harmless stderr is logged.

The success-date marker is updated only after a successful push. If the push failed after a commit, another run retries publication even if the generated data is unchanged. The script fast-forwards from `origin/main`; divergence or conflicts stop with a logged error rather than overwriting work.

To inspect a failed task, check Task Scheduler's last result and the newest transcript. A successful Git push triggers the existing GitHub Pages workflow; its deployment result must be checked separately.

Offline Windows regression tests use temporary local Git remotes and a fake Python executable; they do not contact cinemas or GitHub:

```powershell
python -m unittest discover -s tests -p test_local_refresh.py -v
```

On 2026-09-28 the previous task recorded exit code 1 at 08:58 but saved no error output. A diagnostic rerun of the modified development build succeeded with 3,417 screenings. The original failure's exact cause is unknown; these repairs close verified isolation, logging and publication-result gaps rather than claiming a proven upstream cause.

The scheduled production rerun on 2026-09-28 completed with Windows task result 0. It published 3,410 screenings from all 23 configured cinemas, with zero health alerts. GitHub Pages run `36405125717` succeeded; the public JSON matched the local output generated at `2026-09-28T11:41:36.775561` (Warsaw time). The diagnostic and production runs occurred at different times, so counts differ slightly. Publisher tests cover stderr, build failure, wrong branch, staged changes, failed-push recovery, live routing and Polish transcript output.
