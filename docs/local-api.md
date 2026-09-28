# Local database and screening API

This is a development service, not a deployed replacement for the static site.
It imports existing JSON into SQLite and exposes stored screenings. An explicit
collector command now fetches fresh cinema/date scopes into the same database.
No scheduled worker is installed. The frontend still uses its original JSON.

From the development checkout, after `uv sync --locked`, initialize a new local
database and import the existing source file (one command at a time):

```sh
uv run --locked python -m cinema_agg.server.data migrate
uv run --locked python -m cinema_agg.server.data import-json dist/showtimes.json --source-timezone Europe/Warsaw
```

These commands have already been run in the current development checkout. They
are safe to repeat: migrations preserve rows and identical reimports are no-ops.
The ignored database is `data/cinema-development.sqlite3`. It is not pushed to Git.
Then start the server:

```sh
uv run --locked python -m cinema_agg.server
```

The process stays in that terminal until Ctrl+C. Then request
`http://127.0.0.1:8000/api/v1/screenings?limit=5` from a browser or another terminal.
Expected: JSON containing `snapshot`, `total` and `screenings`. There is no web interface at `/`;
a 404 there is expected. Starting the command is required before opening the URL.

## Configuration and boundaries

Only process environment variables are read; `.env` is not loaded. Optional
`CINEMA_API_HOST` accepts `127.0.0.1` or `::1`; `CINEMA_API_PORT` accepts
1024–65535 (default 8000). `CINEMA_API_DATABASE_PATH` selects the SQLite file,
relative to the launching directory unless absolute. The data CLI's `--database`
option, placed before its subcommand, overrides that path for operator commands.
Unknown `CINEMA_API_*` settings fail startup to catch
typos. Invalid input exits with code 2 and a value-free configuration hint.
The host restriction is intentional until the reverse proxy/deployment work.

The runner disables proxy-header trust, default access logs, debug mode, API
documentation endpoints and the server-version header. Uvicorn serves a single
process. Startup/shutdown use FastAPI's lifespan context; shutdown has a ten-second
grace period. No automatic reload or detached service is installed here.

## What the health check proves

`/health/live` proves the process can answer an HTTP request. It says nothing about
cinema availability, worker progress, database readiness or data freshness.
`/health/ready` additionally checks that the database can be read and the expected
schema is present; it returns 503 for a missing/incompatible database. An initialized
empty database is ready, but its screenings response has `snapshot: null` and no rows.
Readiness does not claim source freshness or collection success. Responses use `no-store`.

## Fresh screening collection

Run `migrate` after updating the checkout to apply the collection tables. A small
live pilot has already fetched 33 Kinoteka screenings for September 29 into this
checkout's database. To collect a chosen cinema/date yourself:

```sh
uv run --locked python -m cinema_agg.server.collector --cinema kinoteka --start 2026-09-29 --days 1
```

Choose the intended date rather than blindly reusing the example. Without `--start`,
the command uses today's Warsaw date. Repeat `--cinema ID` for selected configured
cinemas; `--cinema all` selects all of them. `--days` accepts 1–14, default 1.
Calls are sequential, with a 45-second pause between scopes, a 180-second outer
timeout and the legacy adapters' existing internal request/detail-fetch behavior.
One cinema/date can require multiple requests. A full 23-cinema, 14-day run is
therefore lengthy. No outer automatic retry or request acceleration is added.
An explicit 403/429 propagated by an adapter stops further requests for that run;
remaining scopes are recorded as `cooldown_skipped`. Adapters that swallow errors
still appear as `empty_unconfirmed`; improving those adapters is the next hardening task.

Each result is saved to `fetch_results` and printed as sanitized JSON with cinema,
date, outcome, new/previous counts, duration and exception class when relevant.
Raw legacy stdout is discarded because it can contain booking URLs/errors.
`fetch_runs` records running/complete/partial/failed/interrupted state. Exit codes:
0 = every requested scope accepted, 1 = partial/failed outcomes, 2 = setup/publication
failure. This is a result for the requested scopes, not all cinemas/all dates.

Empty output is `empty_unconfirmed`, never proof of an empty repertoire. Exceptions,
wrong cinema/date and drops of more than 50% retain previous rows for that scope.
Accepted scopes replace their rows in a newly assembled snapshot; untouched scopes
keep their original `scraped_at`. Observed rows get a fresh UTC collection timestamp.
All scope updates and the successful run marker publish in one transaction at the
end. Failed runs publish no snapshot. The API remains able to read previous data
while fetching is in progress. No `dist/` files, poster cache or GitHub Pages are written.

The `collection` object in the API response describes the latest attempt and its
scope outcomes. A new snapshot generation time is an assembly timestamp, not proof
every included row was just fetched. Check `scraped_at` and the relevant scope
outcome. `complete` means all requested outputs passed these checks; legacy adapters
can silently skip malformed rows, so this is not yet proof of upstream completeness.
The pilot does not establish that every provider works from the VPS.

A unique database index blocks overlapping collectors. Normal interruption releases
that lock and leaves previously published data intact. After a hard crash, first
confirm the old collector process has stopped, then explicitly release its run:

```sh
uv run --locked python -m cinema_agg.server.data abandon-fetch RUN_ID
```

Never abandon an active run to start another. Abandoned runs cannot publish; a
concurrent manual import also causes stale collector publication to be refused.
Automatic leases/recovery and alerts belong to the unattended-service milestone.

## Data contract and pagination

`GET /api/v1/screenings` returns all stored screening dates, including past ones.
Parameters: `limit` (1–200, default 50), `offset` (0–50000, default 0), optional
exact `cinema_id`, and optional 64-character `snapshot_id`. Results sort by UTC
start, then original row position. `total` is the count after filtering.

The response includes source generation time, local import time, declared source
timezone and source row count. Dates are UTC with `Z`. `next_offset` is null at the
end. For later pages, pass the returned snapshot ID to stay on the same data even
if a new import occurs. Missing snapshot IDs return 404; invalid parameters 422.
Queries use bound SQL parameters and execute outside the async event loop.

## Import rules and limitations

- The import validates the entire file before writing; inserts commit atomically.
  A parse/validation/database failure cannot replace the last valid snapshot.
- Each import appends an immutable snapshot. Identical file bytes and timezone
  produce the same ID. A different import must have a newer generation timestamp;
  older/conflicting sources are rejected. No automated retention/deletion yet.
- Every source row survives, including identical-looking screenings. IDs are
  **snapshot-scoped row identities**, not durable provider event IDs. This schema
  does not yet support reschedule reconciliation or seat jobs. Those need validated
  provider event/hall identity and separate migrations before production ingestion.
- Legacy runtime `0` becomes `null`. Known Iluzjon `filmy/` and `repertuar/` links
  resolve against its official website origin. Other non-HTTP(S) links fail import.
  This validates URL form only, not whether the booking page still works.
- Naive timestamps are interpreted using the explicit `--source-timezone`. For
  these Windows-generated files use `Europe/Warsaw`; verify the source clock for
  other files, especially GitHub-generated exports. Existing offsets take precedence.
  Ambiguous/nonexistent DST times fail rather than being guessed. Storage is UTC
  integer milliseconds, so sub-millisecond precision is intentionally truncated.
- Empty input is rejected to avoid replacing useful data accidentally. The legacy
  JSON cannot establish complete per-cinema fetch success: importing a newer file
  does **not** prove every cinema fetched successfully. It is a bootstrap mechanism,
  not the future production refresh/reconciliation policy.
- Source limit: 50 MiB / 50,000 screenings. No network requests, automatic retries
  or remote import endpoint. SQLAlchemy manages local transactions; committed
  Alembic migrations are run explicitly, never during API startup or requests.
- API SQLite connections use `mode=ro` plus `query_only`; they cannot create missing
  files or change data. Writes use a five-second busy timeout and serialize with
  `BEGIN IMMEDIATE`. Reads see one consistent snapshot per request.
- This local slice uses SQLite DELETE journal mode. The checked Windows Python
  links SQLite 3.49.1; its WAL-fix status is not established. WAL is deliberately
  not enabled. Patched runtime verification, backup/restore, WAL/concurrency load
  testing and durable event identity remain Phase 2 production gates.

## Logs and troubleshooting

Each application event is one JSON line with a UTC timestamp, level and service.
Request completion adds a generated request ID, HTTP status and duration in ms.
The same ID appears in `X-Request-ID`, and in a generic 500 error body when a
handler fails. Caller-provided IDs are ignored. Lifecycle events identify startup
and clean shutdown; request failures include the exception class.

The formatter uses an allowlist. It excludes raw messages/tracebacks, request URLs,
query strings, headers, bodies, client addresses and environment values. Uvicorn
messages become generic `runtime_event` entries. This deliberately limits current
diagnostic detail: safe stack-location/error categories should be added as concrete
backend failure modes appear, rather than logging arbitrary exception text.
These are operational logs, not visitor analytics. Retention/rotation belongs to
the later systemd/journald host configuration.

If nothing responds, check that the terminal process is running, that startup did
not exit, and that the port is not already occupied. Use another allowed port via
`CINEMA_API_PORT` when needed. No firewall or public VPS port changes are required.

## Validation and next slice

Offline tests cover health, 404s, lifecycle, unique correlation IDs, generic 500s,
log privacy and invalid settings. Strict mypy and broader Ruff checks apply to
the new server modules. The wheel check imports the installed API as well.

Still pending in Phase 1: separate worker heartbeat/shutdown skeleton, host audit,
SSH/service identities and permissions, systemd units and verified restart/reboot.
Phase 2 has begun with this snapshot schema and read-only API. Backup/restore,
production event identity and the host/WAL gate remain open. The live main checkout
remains separate. Tests cover atomic rollback, read-only enforcement, duplicate
and simultaneous imports, pagination pinning, timezone/DST handling and schema errors.

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
and [Uvicorn settings](https://www.uvicorn.org/settings/),
[SQLAlchemy SQLite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html),
[Alembic configuration](https://alembic.sqlalchemy.org/en/latest/api/config.html).
