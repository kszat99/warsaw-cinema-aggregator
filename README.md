
# Warsaw Cinema Aggregator

Warsaw cinema showtimes collected by Python adapters and displayed in a static HTML/CSS/JavaScript frontend. Experimental scripts also inspect aggregate seat availability. The server application described in [the roadmap](ROADMAP_SERVER_APP.md) is planned, not yet implemented.

## Current development setup

Use Python 3.13 (3.12 is also tested) and uv 0.12.19. From the repository root:

```sh
python -m pip install uv==0.12.19
uv sync --locked
uv run --locked pytest -q
```

`uv sync` creates the development `.venv` and installs the project plus development tools from `uv.lock`. No activation is necessary with `uv run`. The lock records exact dependency versions and download hashes; commit it alongside `pyproject.toml` when intentionally changing dependencies. Hatchling builds the installable Python package.

The optional `curl_cffi` transport changes how Multikino requests are made. Enable it explicitly with `uv sync --locked --extra impersonation`, then use the same `--extra impersonation` on `uv run`. The base environment uses the existing httpx fallback. Browser-based research tools still require a separately installed Chrome; a pinned production browser is deferred to provider migration.

GitHub **Development checks** runs tests on Linux/Python 3.12 and 3.13 and Windows/Python 3.13, a focused Ruff correctness check, a fresh wheel installation, source secret scanning and a runtime dependency advisory audit (including the optional transport). Tests block external Python socket connections; Windows publisher tests use temporary local Git repositories. Installation and advisory checks require the internet, but do not contact cinemas. New backend modules will receive broader lint/type checks.

`requirements.txt` is a generated, hashed base-runtime compatibility export, not the source of dependency decisions. Regenerate it with:

```sh
uv export --locked --no-dev --no-emit-project --output-file requirements.txt --quiet
```

Keep the live publisher's checkout/environment separate from this development environment. These checks do not deploy the site or update the VPS.

The tests document current behavior; some experimental behaviors still need correction before production, as recorded in the roadmap. Passing these tests does not validate every upstream website or cutoff policy.

## Local API foundation

The development branch now includes a local FastAPI health service, validated
configuration and structured request logs. It does not yet serve cinema data.
See [local API instructions and boundaries](docs/local-api.md) for the single
startup command and how to check it. The public static website is unchanged.

## Configuration

`TMDB_API_KEY` is an optional process environment variable used to look up missing posters. With no key, cached/source-provided posters remain usable and new TMDB lookups are skipped. Screening collection does not require it.

[.env.example](.env.example) documents the variable. It is a template only: the application does not automatically load `.env` files. Configure the environment of the process that launches the application; never put real credentials into source or example files. If a previously committed key is live, revoke/rotate it at the provider before configuring a replacement.

A live showtime refresh contacts cinema websites and writes files under `dist/`:

```sh
uv run --locked python -m cinema_agg.build
```

The legacy `python -m src.cinema_agg.build` command remains usable from the repository root for existing launchers.

## Research and repository state

Seat probes under `scripts/` are research tools, not the production worker. Unavailable seats are not verified purchases. See [repository preparation notes](docs/repository-preparation.md) for file classifications, credential review and preserved experiment findings.

Temporary profiles, local credentials and runtime data should remain outside Git. Existing tracked generated files are still tracked even when an ignore rule matches; the current Pages deployment depends on committed `dist/` data.
