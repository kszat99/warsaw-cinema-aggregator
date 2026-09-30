# Kinoteka analytics pilot on the VPS

Scope: Kinoteka only. The pilot uses the read-only occupancy endpoint over verified
HTTPS; it never selects, reserves or purchases seats. Other providers remain disabled.

## Inspect it

### Storage and backup rotation

The daily backup service now uses `cinema_agg.server.backups`. It validates a new
SQLite copy before pruning anything, retaining the newest copy on each of seven
distinct dates plus one copy from each of four older ISO weeks (at most 11 managed
files). Only exact `managed-backup-<timestamp>.sqlite3` names are pruned; legacy,
manual, pre-migration, malformed and symlink files are not deleted. Failed backup
creation never prunes earlier copies. Existing manual copies need operator review
if they consume too much space; primary screening/seat data is not purged.

Health uses filesystem modification time to choose the latest backup, avoiding
alphabetical precedence of `backup-pre-*`. Status shows database bytes, backup
total/count and free/total disk. Warnings trigger below 15% free or 1 GiB free, and
when local backups exceed an initial 2 GiB budget. The budget warns; it never deletes
protected copies or the live database. This is local retention, not offsite backup.

### Cinema City readiness (not scheduled)

`python -m cinema_agg.server.cinema_city_probe` fetches tomorrow's Arkadia schedule,
selects the earliest screening and attempts the read-only presentation/layout/status
flow. It neither inserts jobs in the Kinoteka database nor enables another worker.
It stops on 403/429, uses validated booking origins and does not classify generic
HTTP errors or empty maps as confirmed closure. Status keys must belong to the layout;
the status response is sparse: every returned coordinate is available, while omitted
coordinates are unavailable. Values are ticket metadata, not occupied/free flags.
September 29 VPS result: 77 September 30 screenings fetched; Marsupilami at 09:00
(`1717810`) returned 403 at the presentation step. No seat counts were obtained.
September 30 correction: restored the experiment's User-Agent/Accept headers, accepted
integer reservation metadata and corrected sparse status parsing. The site's public
`_nuxt/5506d9d.js` functions `updateSelectedPresentationSeats` and
`updateSelectedPresentationSeatsStatus` confirm these semantics. VPS readiness now
succeeds: 74 October 1 screenings; Odyseja at 09:30, presentation 1709930,
157 available / 29 unavailable / 186 capacity.
[Booking](https://tickets.cinema-city.pl/api/order/1709930?lang=pl).
Unavailable does not mean purchased; counts also precede any UI-specific isolated-seat
selection restrictions. This sample proves access/count parsing, not sustained coverage.
Unattended Cinema City remains disabled pending provider-aware jobs, offsets and
worker/alert integration; the existing Kinoteka worker remains unchanged.

`cinema-pilot-status` and `cinema-pilot-health` now show the same full report.
WHY THIS STATUS explains every warning first. All affected jobs and failed scheduled
attempts in the selected window follow, even when older than the five recent results.
Records show film, screening/planned/attempted/finished times in Warsaw, delay,
deadline, result, HTTP status, counts and correlation IDs. Next checks appear last.
Each failed scheduled attempt also shows its later recovery timestamp and counts,
or UNRESOLVED. Recovery identifies whether the success was a retry of the same job
or a separate scheduled check; it never fills in the original missing snapshot.
Manual diagnostics are labelled explicitly, never as a screening-time check.
Never-attempted jobs have no counts; their startup cause cannot be inferred reliably
because the original database did not record why the attempt was skipped.
The three initial Skarpetki checks at 09:25/09:30/09:35 Warsaw on September 29
predated deployment, as verified during operator review. Historical warnings remain
visible for the selected window and do not necessarily indicate a current outage.

Health report (read-only, no cinema requests):

```sh
sudo cinema-pilot-health
sudo cinema-pilot-health --json
```

Defaults to a rolling 24 hours; `--hours 48` expands the window (maximum 168).
Reports heartbeat age, last complete refresh and per-date current/previous counts,
seat coverage, failed attempts, missed/overdue jobs, maximum start delay and local
backup age/integrity. Coverage uses scheduled jobs whose two-minute window has
finished; excludes diagnostics, future jobs, superseded jobs and identity conflicts.
Identity conflicts are still flagged separately. Startup misses remain visible;
there is no persisted startup baseline to classify them automatically.
The report flags heartbeat age over two minutes, no complete refresh within seven
hours, running refresh over ten minutes, and missing/invalid/backups over 26 hours.
Backup validation is a SQLite quick check, not an independent recovery guarantee.
Exit codes: 0 healthy, 1 attention (including historical errors in the window),
2 report unavailable. No jobs due is not an error if heartbeat/refresh/backup are fresh.
The report is on demand. Telegram notifications are evaluated by
`cinema-pilot-alerts.timer` every 15 minutes; independent external outage monitoring
is still outstanding. Reports never select/reserve seats or change collection state.

### External evaluator heartbeat

The alerts service loads root-owned mode-600 `/etc/warsaw-cinema/heartbeat.conf`
with `CINEMA_HEARTBEAT_URL`. Only a verified HTTPS `hc-ping.com/<UUID>` success
endpoint is accepted; redirects are disabled. After successful alert evaluation,
one GET is sent with a five-second timeout. Acknowledgement requires HTTP 200 and
the exact body `OK`; Healthchecks can return HTTP 200 for ignored/not-found pings.
Cinema health warnings do not suppress check-ins. Evaluation crashes do suppress
them. Missing configuration disables the optional sender; missing check-ins are
detected externally once the check has been activated.

Configure the external check for 15 minutes plus a 10-minute grace period. The
external Telegram integration and a controlled outage/recovery notification test
must be verified separately; an acknowledged ping alone does not prove alerts work.
Monitoring is passive: no seat collection is stopped to test a check-in.

Local attempts are stored in `/var/lib/cinema-pilot/heartbeat-history.sqlite3`, a
separate small SQLite diagnostics file, with attempted/finished times, outcome and
HTTP status. A pre-request `started` row preserves evidence if the process dies.
Rows older than 30 days are pruned on sending. The URL and response text are never
stored/logged. This disposable history is outside the primary database backup;
it records our delivery attempts, not authoritative uptime. The normal status report
shows its latest attempt and flags failed/stale attempts (over 25 minutes).

### Telegram delivery

Seat failures now use screening-specific incidents (provider cinema ID, event ID
and exact start time). Consecutive failed scheduled attempts belong to one incident;
the next scheduled success for that same identity resolves it. Diagnostics and
successes for other screenings do not resolve it. A later failure opens a new episode.
Incidents are derived from the retained observation history, not the rolling health
window. An unresolved incident does not become recovered just because time passes.
The status report shows active incidents and recently recovered incidents separately
from historical failed attempts/coverage, which are never rewritten.
If failure and recovery both happened before evaluation, one combined recovered
summary is delivered. Recovery delivery retains the same durable retry behavior.
The former aggregate `seat_errors_in_window` alert is retired as `superseded`; the
historical health warning remains. Other operational warnings still use the report's
existing condition-clearance semantics. No provider-wide incident aggregation yet.
Current implementation scans retained attempts to reconstruct episodes; add indexed
incremental processing before scaling to a large retained history.

`alert_state` now distinguishes `pending_open`, `open` (delivered),
`pending_resolved`, and `resolved` (clearance delivered). Legacy open records with
no successful notification are retried automatically. Recurrences reuse the issue
row with a new pending transition instead of inserting a duplicate primary key.
Failed deliveries retain a sanitized error category and next retry time in SQLite;
the status report shows pending deliveries. At most two messages are attempted per
evaluation, with a 15-minute minimum wait after failure. No reminders are sent for
unchanged delivered incidents. Plain text avoids provider titles breaking Markdown.
All operational evaluations use the module CLI, whose OS file lock prevents overlap.
Network delivery happens outside database transactions. Successful HTTP responses
must also contain Telegram `ok: true`; raw responses, URLs and exceptions are not logged.
The existing `evidence` JSON holds delivery metadata; `suppress_until_ms` is used as
the delivery retry timestamp. Operator maintenance suppression is not implemented.
If a send succeeds but the process dies before recording acknowledgement, a duplicate
may occur on retry (at-least-once delivery). A report/database failure exits nonzero
with a sanitized log; external monitoring is still needed to detect total outages.
For non-seat incidents, clearance means the condition left the report, including records aging
out of its 24-hour window; it does not by itself prove a new successful cinema request.

Inspect evaluator runs without exposing its credential configuration:

```sh
sudo journalctl -u cinema-pilot-alerts -n 30 --no-pager
systemctl list-timers cinema-pilot-alerts.timer
```

### Seat request failures

A `network_error` is one failed attempt, with unknown counts. It does not erase
earlier observations or stop the next scheduled check. Completed network-error and
timeout attempts currently have no automatic retry; expired interrupted claims may
be reclaimed only within their two-minute window. Later T+5/T+40 observations are
separate checks, not retries. Preserve the failed timestamp rather than filling it
with counts from a different time. A bounded transient-error retry remains future work.

In the VPS SSH terminal:

```sh
sudo cinema-pilot-status
```

This shows worker heartbeat health, warning evidence, next checks in Warsaw time,
and recent observations. `unavailable` includes reservations/blocked seats; it is
not verified ticket sales or attendance. `diagnostic` is a manual early smoke check,
not a timed observation. Failed observations have null counts, not zero.

The actual SQLite database is `/var/lib/cinema-pilot/cinema.sqlite3`:

```sh
sudo sqlite3 -readonly /var/lib/cinema-pilot/cinema.sqlite3
```

Example queries inside SQLite:

```sql
.headers on
.mode column
SELECT outcome, count(*) FROM seat_observations GROUP BY outcome;
SELECT * FROM seat_observations ORDER BY attempted_at_ms DESC LIMIT 5;
```

Type `.quit` to exit. Times ending in `_ms` are UTC Unix milliseconds. In SQL use
`datetime(attempted_at_ms/1000,'unixepoch')` for UTC. The status helper converts to Warsaw.

CSV export (choose a new filename; existing files are not overwritten):

```sh
sudo -u cinema-pilot /opt/cinema-pilot/.venv/bin/python -m cinema_agg.server.seat_pilot --database /var/lib/cinema-pilot/cinema.sqlite3 export --output /var/lib/cinema-pilot/observations.csv
```

## Runtime

- `cinema-seat-pilot.service`: checks due work every five seconds; plans upcoming
  jobs every minute. systemd starts it at boot and restarts it on failure. No PC or
  SSH session must remain open.
- Timings: T-5, T, T+5 and T+40 minutes from advertised start. Identical timing
  offsets are deduplicated. A two-minute lateness allowance accommodates queueing;
  actual attempt/finish times are stored. Expired windows become `missed`.
- `cinema-pilot-refresh.timer`: refreshes today/tomorrow's Kinoteka screenings every
  six hours. Accepted data feeds the planner; failures retain earlier data.
- Sources older than 48 hours are not used for new checks. An ambiguous provider
  event/start is not guessed; rescheduled pending jobs are superseded.
- Durable job identity includes provider cinema/event ID, screening start, timing
  offset and policy version. Restarting does not duplicate completed jobs. An
  interrupted attempt is retained; expired leases can recover within the deadline.
- One request at a time, at least two seconds apart. 403/429 pauses probing for at
  least 15 minutes (numeric Retry-After can extend this). Generic 404s and missing
  counts are not called closed sales. The endpoint's count response does not prove
  sales are still open or counts reflect final purchases.
- The service runs as `cinema-pilot`, with no login shell, restricted filesystem
  access and memory/CPU limits. No new listening/public port is opened.

The refresh runner owns this isolated database's refresh lock and recovers interrupted
runs after a crash. Do not run the raw generic collector against this database;
use `sudo systemctl start cinema-pilot-refresh.service` instead.

Logs and timers:

```sh
sudo journalctl -u cinema-seat-pilot -n 20 --no-pager
systemctl list-timers 'cinema-pilot-*'
```

Stop collection: `sudo systemctl stop cinema-seat-pilot.service`. To stop automatic
screening refreshes too, stop `cinema-pilot-refresh.timer`. Disable units if they
should remain stopped after a reboot. This does not delete the database.

## Backups and limitations

`cinema-pilot-backup.timer` makes a daily consistent SQLite backup with an integrity
check under `/var/lib/cinema-pilot/backups/`. These are local VPS backups, not an
offsite disaster-recovery solution. No observation retention purge is enabled yet;
review disk usage and backup retention as the pilot grows. SQLite stays in DELETE
journal mode while the planned WAL/runtime verification remains outstanding.

The pilot is the first running data collection slice, not a claim of full cinema
coverage, externally monitored availability, or completed production hardening.
The public website remains on its existing deployment.

## Installation/update boundary

`deploy/install-seat-pilot.sh` installs a new isolated pilot from a reviewed wheel
and hashed requirements, migrates explicitly and verifies systemd units. It refuses
to overwrite an existing pilot DB. For updates: stop the worker/timers, make a
consistent backup, install the reviewed package, run migrations explicitly, verify
readiness and restart. Preserve the previous package and backup for rollback; do not
downgrade schemas destructively. The installed Git revision belongs in
`/opt/cinema-pilot/RELEASE`.
