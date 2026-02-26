# Warsaw Cinema Aggregator (v1)

Personal project to aggregate screening times from multiple Warsaw cinemas by scraping their repertoire pages, normalizing results into one schema, and exporting **static JSON snapshots**.

The key idea:
- You run a **builder script** that fetches + parses cinema pages.
- The builder outputs `dist/showtimes.json`.
- Later, you can host the static page on GitHub Pages and refresh the JSON via GitHub Actions — **no always-on PC**, no server.

---

## Goals (v1)

- Support “friendly” cinemas first (server-rendered HTML).
- Normalize into one shared `Screening` schema.
- Export a single JSON file:
  - `dist/showtimes.json`
- Optional: Use SQLite **only as build-time cache** (no DB server).

---

## Supported cinemas (initial list)

Friendly (good candidates for plain requests + HTML parsing):
- https://kinomuranow.pl/repertuar
- https://kinoluna.bilety24.pl/
- https://kinoelektronik.pl/
- https://wisla.novekino.pl/MSI/mvc/pl
- https://atlantic.novekino.pl/MSI/mvc/pl

Later (likely requires API discovery or dynamic parsing):
- https://kinoteka.pl/repertuar/
- https://www.cinema-city.pl/ (Arkadia, Bemowo, Sadyba/IMAX)
- https://www.multikino.pl/repertuar/warszawa-mlociny/teraz-gramy

---

## Tech stack (v1)

- Python 3.11+ (3.10 OK)
- `httpx` — fetching
- `beautifulsoup4` + `lxml` — parsing HTML
- `pydantic` — validated data models + JSON export
- `python-dateutil` — parsing/handling dates (optional but helpful)
- SQLite (`sqlite3`) — **built into Python** (optional cache)

Later (phase 2):
- `playwright` — for dynamic sites (Cinema City / Multikino)

---

## Project structure

Create a repo folder, e.g. `warsaw-cinema-aggregator/`

```
warsaw-cinema-aggregator/
  src/
    cinema_agg/
      __init__.py

      config.py          # timezone, enabled cinemas, output paths, timeouts
      models.py          # Pydantic models: Cinema, Screening, BuildOutput
      fetch.py           # HTTP client wrapper + retries + headers
      normalize.py       # title normalization, tags parsing, dedupe uid

      adapters/
        __init__.py
        base.py          # adapter interface/contract
        muranow.py
        novekino.py
        luna_bilety24.py
        elektronik.py

      storage/
        __init__.py
        sqlite_cache.py  # optional: cache raw HTML by (cinema_id, date) with TTL

      build.py           # orchestrator: run adapters, normalize, export JSON

  dist/
    .gitkeep             # output directory for showtimes.json

  data/
    .gitkeep             # cache.sqlite and any raw-html cache

  tests/
    test_normalize.py

  requirements.txt
  README.md
```

---

## Installation (PyCharm / local)

1) Create a new project in PyCharm and point it at the repo folder.
2) Create a virtualenv (PyCharm usually offers it automatically).
3) Install deps:

```bash
pip install -r requirements.txt
```

4) In PyCharm, mark `src/` as Sources Root:
- Right click `src/` → **Mark Directory as** → **Sources Root**

5) Run the builder:

```bash
python -m cinema_agg.build
```

Output should appear as:
- `dist/showtimes.json`
- optionally `data/cache.sqlite` (if caching enabled)

---

## requirements.txt (v1)

Create `requirements.txt`:

```txt
httpx>=0.27.0
beautifulsoup4>=4.12.0
lxml>=5.2.0
pydantic>=2.7.0
python-dateutil>=2.9.0
```

(SQLite comes with Python, no install needed.)

---

## Data model (v1)

### `Screening` (one showtime)

Required fields:
- `cinema_id`
- `cinema_name`
- `source_url`
- `starts_at` (ISO 8601 with Europe/Warsaw offset)
- `local_date` (YYYY-MM-DD)
- `local_time` (HH:MM)
- `title_raw`
- `title_norm`
- `booking_url` (nullable if not available)
- `scraped_at` (UTC ISO time)

Recommended optional fields:
- `format` (e.g. `["2D", "IMAX"]`)
- `subtitles` (`"pl"`, `"en"`, `"none"`, `"unknown"`)
- `dubbed` (bool)
- `duration_min` (int)
- `event_type` (`"regular"`, `"preview"`, `"special"`, ...)

### Dedupe key

Generate a stable UID per screening:
- `sha1(cinema_id + starts_at + title_norm + (booking_url or ""))`

---

## Adapter contract (important)

Each cinema is implemented as an adapter module under `adapters/`.

Every adapter should:
- Define `cinema_id`, `cinema_name`, and `source_url`
- Implement:
  - `fetch(date) -> str` (HTML or raw text)
  - `parse(date, raw) -> list[Screening]`

The `build.py` orchestrator:
- picks date range (e.g. today + 7 days)
- calls each adapter
- normalizes + dedupes
- exports JSON

---

## SQLite caching (optional, build-time only)

Important: **You do NOT host SQLite on the internet.**
SQLite is only used when running the build script (locally or in CI).
It’s just a file (e.g. `data/cache.sqlite`) — no server.

Suggested use:
- Cache raw HTML by `(cinema_id, date)`
- If cached data is newer than TTL (e.g. 2 hours), skip refetch

If you later run this via GitHub Actions:
- Either skip caching (simplest), OR
- Use GitHub Actions cache to persist `cache.sqlite` between runs.

---

## v1 milestone plan

Day 1:
1) Implement `models.py`, `build.py` that outputs **dummy** data to JSON.
2) Implement the first real adapter:
   - Recommended starting point: **Novekino** (Wisła + Atlantic share structure)
3) Confirm end-to-end: running build produces valid `dist/showtimes.json`.

Then add:
- Muranów
- Luna (Bilety24)
- Elektronik

Phase 2:
- Cinema City / Multikino via Playwright or API endpoint discovery.

---

## Next steps

Once local build works:
- Add a simple static frontend (HTML + JS) to read `dist/showtimes.json`.
- Publish to GitHub Pages.
- Add GitHub Actions schedule to refresh JSON automatically.

No server needed, no PC running all the time.
