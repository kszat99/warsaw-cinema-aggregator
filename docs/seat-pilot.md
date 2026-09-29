# Kinoteka analytics pilot on the VPS

Scope: Kinoteka only. The pilot uses the read-only occupancy endpoint over verified
HTTPS; it never selects, reserves or purchases seats. Other providers remain disabled.

## Inspect it

In the VPS SSH terminal:

```sh
sudo cinema-pilot-status
```

This shows whether the worker is active, job states, the next check in Warsaw time,
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
