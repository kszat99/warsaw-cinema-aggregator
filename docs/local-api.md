# Phase 1: local API foundation

This is a development service, not a deployed replacement for the static site.
It does not fetch cinemas, expose screenings, open a database or run a worker.

From the development checkout, after `uv sync --locked`:

```sh
uv run --locked python -m cinema_agg.server
```

The process stays in that terminal until Ctrl+C. Then request
`http://127.0.0.1:8000/health/live` from a browser or another terminal.
Expected: HTTP 200 and `{"status":"ok"}`. There is no web interface at `/`;
a 404 there is expected. Starting the command is required before opening the URL.

## Configuration and boundaries

Only process environment variables are read; `.env` is not loaded. Optional
`CINEMA_API_HOST` accepts `127.0.0.1` or `::1`; `CINEMA_API_PORT` accepts
1024–65535 (default 8000). Unknown `CINEMA_API_*` settings fail startup to catch
typos. Invalid input exits with code 2 and a value-free configuration hint.
The host restriction is intentional until the reverse proxy/deployment work.

The runner disables proxy-header trust, default access logs, debug mode, API
documentation endpoints and the server-version header. Uvicorn serves a single
process. Startup/shutdown use FastAPI's lifespan context; shutdown has a ten-second
grace period. No automatic reload or detached service is installed here.

## What the health check proves

`/health/live` proves the process can answer an HTTP request. It says nothing about
cinema availability, worker progress, database readiness or data freshness. There
is deliberately no readiness endpoint until actual dependencies can be checked.
Health/error responses are marked `no-store`.

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
Database/schema readiness comes in Phase 2. The live main checkout remains separate.

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
and [Uvicorn settings](https://www.uvicorn.org/settings/).
