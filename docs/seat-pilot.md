# Cinema seat collection on the VPS

## Current timing policy — October 1 evening

Enabled: Kinoteka, seven Cinema City venues (Sadyba IMAX only), Novekino
Wisła/Atlantic and Amondo. Older deployment entries below describe earlier scope.

Historical checks for every provider: T-24h/-12h/-6h/-3h/-2h/-1h/-30m/-15m.

| Provider | Final and later checks |
| --- | --- |
| Kinoteka | T-5, T0, T+5, T+40 |
| Cinema City | T-5, T0, T+5, T+10 |
| Wisła | T-5, T-2 |
| Atlantic | T-5 |
| Amondo | T-5, T-2 |

Repeated successful pre-start observations followed by showtime unavailability
justify retiring routine T0/T+5 for Novekino and Amondo. Amondo evidence establishes
repertoire disappearance, not direct booking closure. Atlantic T-2 is not yet tested.
Removed unattempted pending jobs become superseded and are excluded from coverage;
completed attempts and genuine failures remain unchanged. Manual diagnostics remain
available; occasional cutoff revalidation can be added separately.

Post-start sales_unavailable (Wisła/Atlantic) or listing_absent/sales_unavailable
(Amondo), backed by a successful T-5/T-2 scheduled observation of the exact same
screening before start, are labelled EXPECTED CUTOFF. Existing notifications are
marked resolved with resolution=expected_cutoff without a fabricated recovery message.
Health retains evidence and the last pre-start seat count, but these observations do
not trigger an open incident. Earlier technical failures in the same incident prevent
this retirement. Pre-start unavailability, network/HTTP/validation failures and misses
remain actionable. Historical unrelated problems may still produce ATTENTION.

## Earlier deployment history


Scope: Kinoteka and Cinema City Arkadia (catalogue ID 1074). Verified HTTPS and read-only
occupancy/layout/status requests; never selects, reserves or purchases seats. Other
venues remain disabled. Shared database/worker, independent provider cooldowns.

September 30 deployment evidence (Warsaw time): combined refresh completed 09:39:05,
accepting 74 Arkadia screenings today and 74 tomorrow, plus 33/day for Kinoteka.
592 scheduled Arkadia checks queued. Stored diagnostic 09:39:23 for Lalka at 10:00
(presentation 1709363): 120 available / 252 unavailable / 372 capacity. First automatic
Arkadia checks due 09:55; sustained scheduled coverage remains to be reviewed.
Kinoteka completed its 09:40 check after deployment. Telegram accepted a clearly labelled
deployment test; alert evaluation completed with external heartbeat acknowledged 09:40:20.
No active screening incidents or overdue jobs at that verification point.

The upgrade took approximately three seconds between Kinoteka checks. Integrity-checked
pre-upgrade backup: `/var/lib/cinema-pilot/backups/backup-pre-arkadia-20260930.sqlite3`.
Prior wheel/units: `/home/ubuntu/cinema-pilot-rollback-c09afde/`. Rollback requires stopping
worker/refresh/alert/backup services and timers, retaining the current DB, restoring the
old backup and matching package/units, then daemon-reload/restart. Restoring the backup
removes post-upgrade records from the active database; retain the current DB to reconcile
them. Never restore while a writer is running or downgrade schema in place.

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

### Cinema City Arkadia automatic collection and manual readiness

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
Arkadia automatic scheduling is now enabled using this verified probe. Schema
0005_seat_providers preserves existing Kinoteka jobs, adds provider/cinema labels and
records activation on first planning with fresh Arkadia rows. Earlier check times are
skipped, not counted as missed. Subsequent missed windows remain visible normally.
Kinoteka offsets and job IDs are unchanged.

Status shows each cinema's coverage, confirmed closures, missed windows and pending
checks. Telegram alerts name the cinema and screening; existing 15-minute evaluation
and durable delivery retries apply. Successful checks do not send routine notifications.
Explicit sales closure keeps counts null, is separate from failures and successful seat
counts, and cannot resolve an earlier failure without a later successful seat observation.

Stored manual diagnostic (excluded from scheduled coverage):

```sh
sudo -u cinema-pilot /opt/cinema-pilot/.venv/bin/python -m cinema_agg.server.seat_pilot --database /var/lib/cinema-pilot/cinema.sqlite3 probe-next --cinema 1074
```

The shared claim lease prevents overlapping observations. A busy worker can leave this
command without a claimable diagnostic; prefer normal scheduled collection, not repeated
manual probes. The standalone readiness command above does not write observations.

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
earlier observations or stop the next scheduled check. Schema `0006_seat_retry` enables
one automatic retry, 30 seconds after a first scheduled network error or timeout.
It requires 20 seconds remaining for Kinoteka or 60 for Cinema City's three requests,
after that delay and inside the original two-minute deadline. Claiming rechecks the
budget; queue delays or provider cooldown can make a retry ineligible. Waiting does
not block other jobs. Eligibility persists across restart and source refresh.

TLS/certificate errors, blocks/429, HTTP errors, invalid data, confirmed closure and
manual diagnostics do not retry. No third request attempt is scheduled. Historical
completed failures are not reopened. Numeric provider Retry-After/cooldowns still apply.
A retry returning after the original deadline is recorded as `deadline_exceeded` with
unknown counts, not successful coverage. The time reserve is conservative scheduling,
not a hard cancellation of an already-running HTTP operation.

Both attempts retain separate timestamps and outcomes under the same job. Status lists
waiting retry times, skipped/exhausted retries, and whether recovery was a same-window
retry or a later scheduled offset. Success on retry counts once toward job coverage;
the original failed attempt remains visible. Maximum start delay includes retries.
Telegram uses the same incident/recovery delivery, with explicit same-window recovery
wording. Later T+5/T+40 observations remain separate checks, not retries.

September 30 retry rollout: pre-upgrade backup
`/var/lib/cinema-pilot/backups/backup-pre-retry-20260930.sqlite3`; previous wheel under
`/home/ubuntu/cinema-pilot-rollback-00df19f/`. Existing jobs/observations preserved;
worker and all timers restarted after the schema migration. Retry behavior is verified
with offline injected failures; no artificial outages were introduced into live jobs.
Release `535b234` passed all GitHub CI jobs (149 tests). After deployment, the first
five Arkadia scheduled checks succeeded between 09:55:04 and 09:55:25 Warsaw, with
no overdue jobs or active incidents. All five succeeded on their first attempt; this
verifies scheduled dispatch after migration, not a live retry recovery. External
heartbeat and alert evaluation also succeeded at 09:54:43.

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
- Timings: Kinoteka T-5/T/T+5/T+40; Arkadia T-5/T/T+5/T+10. Identical timing
  offsets are deduplicated. A two-minute lateness allowance accommodates queueing;
  actual attempt/finish times are stored. Expired windows become `missed`.
- `cinema-pilot-refresh.timer`: refreshes today/tomorrow's Kinoteka and Arkadia screenings every
  six hours. Accepted data feeds the planner; failures retain earlier data.
- Sources older than 48 hours are not used for new checks. An ambiguous provider
  event/start is not guessed; rescheduled pending jobs are superseded.
- Durable job identity includes provider cinema/event ID, screening start, timing
  offset and policy version. Restarting does not duplicate completed jobs. An
  interrupted attempt is retained; expired leases can recover within the deadline.
- One observation at a time, at least two seconds between observations; Arkadia uses
  three sequential read-only requests per observation. 403/429 pauses only that provider
  for at least 15 minutes (numeric Retry-After can extend this). Generic 404s and missing
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

## Schedule warnings and elapsed screenings (September 30 correction)

A refresh updates screening times; the seat worker is a separate process. A partial
refresh accepts successful cinema/date updates and retains previous data for rejected
ones. The seven-hour warning measures time since a fully accepted refresh, so a partial
run can cause both a partial and later age warning without a second network outage.

Count-drop validation compares previously upcoming and newly returned upcoming
screenings at the same fetch-completion instant, ignoring elapsed screenings. A greater
than 50% upcoming drop is quarantined; an empty response is still unconfirmed, never
treated as proof of closure. Schema 0007 records both counts. Older runs lack those
counts and are labelled as legacy full-day comparisons in incident explanations.
The terminal and Telegram show affected venue/date, counts, retained-data impact and
separate seat-collection evidence. Recovery reports the actual latest refresh status.

After investigating the cause, rerun with:
sudo systemctl start cinema-pilot-refresh.service
This uses the existing pacing and lock; do not restart the seat worker for schedule warnings.

## Novekino Wisła pilot

Wisła uses its own msi_wisla provider budget/cooldown and durable T-5/T/T+5 jobs.
Each observation opens a fresh MSI session: repertoire GET, Default.aspx GET with
date-specific returnlink, hidden ASP.NET state POST, and same-origin redirect to
OrderTickets.aspx. No seat identifiers are posted, and cookies are cleared after
every observation. TLS verification remains enabled. Counts require both explicit
capacity/availability labels and matching unique available checkbox controls.
Missing handshakes/maps or mismatches are invalid_data, never closed or zero seats.
Closure recognition remains unproven; a T+5 technical failure may need review.

The initial pilot does not immediately retry Wisła failures: its conservative 120s
retry reserve exceeds the remaining window after the retry delay. Later offsets
remain independent checks, and normal incident recovery can close an earlier failure.
403/429 applies an independent minimum 15-minute cooldown; numeric Retry-After is
honoured. Redirects are limited and restricted to the Wisła HTTPS MSI origin.
Per-request timeout is 10 seconds. Other MSI venues remain disabled.

Schedule refresh includes Wisła today/tomorrow from the next regular run. Initial
September 30 evening seed fetches only October 1 (September 30 bookings have ended);
it preserves the already accepted Kinoteka and Arkadia snapshots.

## Historical seat observations — October 1

All three enabled providers now collect at T-24h, -12h, -6h, -3h, -2h, -1h,
-30m, -15m and -5m. Kinoteka retains T/T+5/T+40, Arkadia T/T+5/T+10.
Wisła adds T-2m and retires only unattempted pending T/T+5 jobs; existing attempts
and Kura's failure incident are preserved. There is no fabricated recovery.

Early snapshots (T-30m and earlier) have a deterministic 0–59.999s spread.
Due time stores the actual spread target; actual attempt time remains separate.
Near-start observations are exact. Existing sequential worker/provider cooldowns
still apply. Upcoming slots are planned once; slots already passed when introduced
are not backfilled and do not create missed jobs. Full curves require screenings
to be discovered at least 24 hours ahead.

Wisła T-2 requires >60s remaining before showtime at claim time. If not, state becomes
cutoff_skipped; report displays the count and excludes it from coverage. Each MSI
request/redirect checks the showtime cutoff and uses the remaining request timeout.
A response arriving at/after showtime cannot retain counts; late responses are
deadline_exceeded. A request already in flight can finish late, but no subsequent
request is started after the cutoff. T-5 remains the fallback.

These are observed available/unavailable counts, not confirmed purchases. Traffic
increases with the number of screenings; review burst delays, rate limits and coverage
before expanding. The retained post-start Kinoteka/Arkadia observations remain useful
for final-count/cutoff validation.

## Cinema City expansion — October 1

All seven Cinema City venues on the legacy page are explicitly enabled: Arkadia,
Bemowo, Sadyba (IMAX only), Galeria Mokotów, Promenada, Galeria Północna and Janki.
They share one cinema_city cooldown/retry budget and the existing sequential worker.
A block/rate limit applies to the whole chain. Stable identities include catalogue
cinema plus presentation ID; network dispatch requires those cinema IDs to agree.
No other provider is automatically enabled from the legacy catalogue.

Fresh VPS tomorrow-booking probes passed for all six new venues:
Bemowo 143 available / 24 unavailable / 167 total (presentation 1730784);
Sadyba 318 / 49 / 367 (1728629);
Mokotów 200 / 53 / 253 (1730660);
Promenada 106 / 27 / 133 (1730720);
Północna 130 / 24 / 154 (1730764);
Janki 103 / 43 / 146 (1730740).
These are samples, not sustained-load guarantees.

Regular refresh now covers nine venues and two dates (18 scopes). Existing 45-second
spacing means a healthy run can take around 13 minutes. The service timeout is now
30 minutes, with a stuck warning after 25 minutes. The six-hour timer and seven-hour
freshness threshold stay unchanged. Initial new-venue seed uses a single paced run
with 15 seconds between 12 scopes; subsequent refreshes use the normal 45 seconds.
Existing snapshots and attempts are preserved. Past slots are not backfilled.
Review combined due-job bursts and observed queue delays before further expansion.

Measured expansion forecast: maximum same-time group 55 overall and 20 near-start
checks across current today/tomorrow schedules. Early snapshots (T-15 and earlier)
now have 600 seconds of queue allowance, with their existing spread unchanged.
Near-start checks retain 120 seconds, and Wisła's final cutoff remains stricter.
Earliest-deadline dispatch prioritizes near-start work over queued historical work.
Pending early jobs receive the extended deadline; finished attempts are untouched.
Terminal attempt lines show each job's actual allowance. Historical times are target
times, not a guarantee of exact-minute sampling; use actual attempt timestamps in analysis.
Early Wisła network failures may now have sufficient time for the existing single retry;
near-start Wisła still does not. Combined load needs observation under real failures.


## October 1: Wisła failure evidence and published seat counters

Investigated Lalka event 114487 (14:30): live response publishes 483 available /499
capacity, but contains 482 unique selectable checkboxes. Strict equality incorrectly
rejects this valid page. The parser now accepts published availability on a partial
selectable list only when the separate SeatCount field agrees with published capacity;
duplicated/disabled controls, missing capacity corroboration and impossible counts
still fail. The exact reason for MSI's one-seat discrepancy is unconfirmed; these
are provider-published availability counts, not proof of ticket purchases.

Schema 0008_seat_diagnostics retains bounded (24,000 characters) sanitized response
text, phase, page path, HTTP status and parsing reason for failed Wisła observations.
Scripts/styles/inputs/textareas are removed: cookies, headers and hidden ASP.NET
state are not retained. Evidence is in seat_observations.diagnostics_json and journal;
status shows phase/reason/path without dumping the whole page. Published-count versus
control-count discrepancies are also retained on successful observations. Historical
failures remain unknown; no inferred counts or retrospective recoveries are fabricated.
Retention follows observation history for now; response captures are bounded per record.

At 11:47 Warsaw, Cinema City scheduled coverage was Arkadia 319/319, Bemowo 21/21,
Sadyba IMAX 1/1, Mokotów 16/16, Promenada 22/22, Północna 23/23 and Janki 18/18,
with no missed checks. New venues still require sustained observation.


October 1 follow-up: screening failure/recovery Telegram messages now include the
last failure's specific cause, failed phase, HTTP status, returned page path and
selectable-control count when available. An explicit MSI sales-unavailable message
is surfaced without assuming it means sold out. Old attempts clearly state that no
detailed response evidence was saved. Full bounded sanitized page text remains in
SQLite, not Telegram; raw HTML/session form state is not archived. Existing alert
deduplication and recovery rules stay unchanged. Wisła's next Lalka 14:30 check is
scheduled around 12:30 Warsaw; no additional polling loop is enabled.


October 1: restore Wisła T0 and T+5 observations alongside T-5/T-2 and historical
checks. The Lalka mismatch disproves treating every invalid_data as sales cutoff;
actual closure timing still needs evidence. Future unattempted superseded T0/T+5
jobs for current screening identities are reactivated idempotently; past slots and
attempted/finished history are not rewritten. Strict pre-showtime deadline applies
only to T-2, not the restored checks. Existing serial pacing, request limits and
failure/recovery alerts apply, with sanitized failure text retained. Late purchasing
is a hypothesis to evaluate from observations, not an established fact.


## October 1: Novekino Atlantic collection

Atlantic enabled explicitly as msi_atlantic, separate cooldown from msi_wisla.
History timings T-24h/-12h/-6h/-3h/-2h/-1h/-30m/-15m plus T-5/T0/T+5.
Fresh verified HTTPS MSI session, approved repertoire booking link, ASP.NET tab
handshake only. Atlantic requires preserving same-origin Referer on seat redirect;
framework hdnServer is included, no seat/payment controls are posted. Wisła retains
its existing redirect/session behaviour. Missing labels on Atlantic are handled
using unique selectable controls plus explicit hidden SeatCount corroborated against
known hall A/B/C/D capacities (158/221/259/156); unknown/mismatched halls fail.
Counts mean availability, not purchased tickets. Failure evidence and explanatory
Telegram alerts use the same durable observation/incident system. Closure timing
is still under observation; unavailable/redirected pages do not imply zero seats.
VPS live readiness: October 2 Lalka 11:45, event 47593, 128 available /30 unavailable
/158 capacity. Regular refresh automatically includes Atlantic today/tomorrow.
Ten venues /20 date scopes at 45s spacing fit the existing 30-minute service timeout.


Atlantic follow-up: Verity 48057 T-24h failed because repertoire lookup required
purchase typetran=0, while the cinema advertises this event using typetran=1. The
saved response includes Verity Friday 13:00: event was not actually absent. Lookup
now accepts either advertised transaction mode for the validated event and converts
the entry to purchase typetran=0 before the read-only handshake. No seats are selected.
Regression covers both link modes. Previous missing-link alert reflects our lookup
bug, not proof of cancellation, sold-out status or sales closure.


## October 1: classify availability separately from technical errors

New MSI observations use sales_unavailable only for the explicit provider sales
message; listing_absent only when the repertoire omits the event and a direct
booking fallback returns repertoire rather than a map. Neither outcome implies
sold out or establishes the exact cutoff. Parser/handshake mismatches are
 data_validation_error; network/timeouts/HTTP blocks remain separately classified.
Sanitized failure evidence stays in SQLite. Historical outcomes are not rewritten.
Availability observations have their own status section and are excluded from
technical failed-attempt counts, while missing seat snapshots still lower seat-count
coverage. Availability episodes still generate deduplicated notices and remain
visible as attention until a same-screening success or the historical reporting
window rules apply. Explicit unavailable sales never counts as successful recovery.
Telegram headline SEAT AVAILABILITY UNAVAILABLE distinguishes these from SEAT CHECK
FAILED; includes latest T offset and actual attempt timestamp, cause/path/status,
and omits irrelevant zero controls for repertoire/handshake availability pages.

Atlantic repertoire absence now falls back to the validated numeric event's
Default.aspx entry, preserving same-origin Referer and TLS validation. Bound of four
request hops per phase supports its redirects; Wisła keeps the prior two-hop bound.
No seat controls are posted. VPS read-only test of past Lalka 47590 reached
Message.aspx with explicit sales unavailable, rather than stopping at repertoire
absence. Wisła Tedi 114826 likewise explicitly reports sales unavailable. These
current tests validate classification, not retrospective closure timestamps.


## October 1: SQLite write contention and refresh interruption

14:16 refresh failed acquiring BEGIN IMMEDIATE with SQLITE_BUSY after seven scope
results. The actual competing holder is not identified in logs. Copied VPS DB plan
benchmark: 4.355s for 8,633 jobs; health report 0.112s. Worker CPU quota can extend
planning wall time beyond the original five-second wait. Avoid claiming a proven
holder; redundant planning is a measured contention contributor.

Worker polls latest import ID via autocommit read every minute, rebuilding only
when it changes or after ten minutes (to extend moving horizon). Pending job dispatch
still runs continuously; stable jobs and timings unchanged. SQLite write acquisition
retries SQLITE_BUSY twice, each with existing five-second wait (15 seconds maximum).
Only BEGIN acquisition is retried, before mutations; whole transactions are never
blindly replayed. Non-busy database errors surface immediately. This is bounded lock
waiting, not a new message broker; one writer already serializes SQLite transactions.
Schema 0009_refresh_failure stores planned scope count, safe error type and failed
phase on interrupted runs. Alerts distinguish recorded scopes from planned total,
state whether a snapshot was published, and show database_busy when captured.
Historical runs retain unknown totals/causes; no guessed historical fields added.
A persistent blocker still fails visibly; this does not promise zero future errors.


## October 1: concurrent provider dispatch with conservative shared pacing

Single managed seat-worker process now dispatches up to three independent tasks:
Cinema City (all seven locations), Kinoteka, and Novekino (Wisła + Atlantic). Each
flow owns an HTTP client. One active lease per dispatch group is enforced inside
SQLite claim transactions, as well as by the executor's active-group tracking.
Shared Novekino group serializes both sites and propagates pacing/block cooldown
across them; Cinema City block still pauses all its locations, not other groups.
Minimum five seconds after completion before next same-group flow; bounds/timeouts
and retries unchanged. Global five-second sleep replaced by provider gating and
one-second dispatch polling. Pending checks have the original actual-time evidence
and existing near-start/historical deadlines; no retroactive backfill or fake recovery.
Final pre-start T-5/T-2 checks precede supplementary post-start and historical work,
with earliest deadline ordering within priority class. Single provider can still
exceed its two-minute burst capacity; measure new coverage before changing windows
or request concurrency. No claim of eliminating all future misses.
Regular planner remains one owner with unchanged-snapshot skip and ten-minute horizon
refresh. Threads perform network work outside short SQLite claim/finish transactions.
Health and alerts continue tracking missed slots, actual attempts and provider cooldowns.


## Schedule changes and missing booking verification

Accepted, published cinema/date refreshes retire pending jobs absent from that scope.
Empty/unconfirmed or count-drop-quarantined responses retain the prior schedule and
jobs. Invalid booking identities prevent destructive reconciliation for that scope.
Exact booking/start identities are compared; historical counts are not merged into a
replacement showing. schedule_removals stores the confirming run and verification time.

Cinema City PRESENTATION_NOT_FOUND queues a durable cinema/date refresh request.
The worker performs it in a separate thread, sharing the regular refresh flock;
requests deduplicate by cinema/date and targeted refreshes have global 15-minute
minimum spacing and respect provider cooldown. Restarted requests recover after a
five-minute lease. A missing-only incident has at most 15 minutes verification grace.
If accepted fresh data still lists the broken booking, verification fails, or grace
expires, the alert shows provider error code and booking URL. Confirmed removal
resolves the alert as schedule_changed without claiming a successful seat count.
Health labels SCHEDULE CHANGED or VERIFYING SCHEDULE and retains original attempts.
