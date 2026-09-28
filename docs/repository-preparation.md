# Phase 0 — repository preparation

Initial review: 2026-09-27, covering file inventory, ignore rules and credential configuration. Packaging/CI checkpoint: 2026-09-28, development branch only. No VPS settings or production dependencies changed.

## File decisions

| Files | Treatment |
|---|---|
| `ROADMAP_SERVER_APP.md`, README, configuration example and these notes | Keep as project documentation |
| `src/cinema_agg/seat_availability.py`, seat-related tests | Keep as source/test candidates; still need the planned production review |
| `scripts/monitor_booking_cutoffs.py`, `select_cutoff_targets.py`, `probe_atlantic_seats.py` | Keep as diagnostic/research tools; do not describe them as production collectors |
| `scripts/run_cutoff_investigation.ps1`, `run_targeted_cutoff_2026_09_21.ps1` | Keep reproducible experiment launchers; the dated launcher is historical and should not be used as a current schedule |
| Modified `outputs/seat-review/*` and `scripts/register_local_refresh_task.ps1` | Preserve existing user/session changes; not edited in this preparation step |
| Untracked `tmp/` browser profiles/assets and `outputs/seat-cutoff/` raw artifacts | Ignore; retain all local files |
| Already tracked files under `tmp/` | Remain tracked; assess individually before a later archive/untracking change |
| Already tracked `dist/` showtimes/poster-cache/health | Retain: current deployment uses committed data; migration happens later |

Root research-file exclusions now apply only at the repository root. Nested JSON/HTML/JS fixtures and Python modules can be committed normally. Runtime DB sidecars, logs, PID files, local environment files, private key files and tool caches are ignored; `.env.example` stays visible.

Ignore rules do not remove files already in Git or clean history. Review staged content before any future commit; do not use a blanket add of every research artifact.

## Credential review

- The previous TMDB credential was found in tracked configuration and in six historical configuration revisions reachable from local Git refs. It was not found elsewhere in the tracked working files during the exact-value check.
- The current configuration reads optional `TMDB_API_KEY` from the process environment. No copy of the old credential was written to a local environment file.
- Poster enrichment skips network requests without a key and continues to use cached posters. Existing screening collection remains available.
- Owner action: revoke/rotate the old key in TMDB if it is live. Its current validity was not tested. Removing source text does not revoke historical credentials.
- CI now scans current source/configuration with detect-secrets, without online credential verification or printing values. Generated outputs, temporary captures and Git history are excluded. This is not a guarantee that every credential has been found or revoked.
- The application does not auto-load `.env`; configure the real launching process when a replacement key is ready.

## Preserved experiment findings

Source: local `outputs/seat-cutoff/cutoff-summary-combined-2026-09-27.txt`; this summary deliberately omits raw booking sessions and browser captures. T is the advertised screening start. Access failure is not necessarily sales closure.

| Provider / venue | Recorded evidence and limit |
|---|---|
| Atlantic | Readable around T-2; handshake missing around T-1 in three samples |
| Wisła | First failures at T+2, T+4 or T+10; other samples readable through T+45; no consistent cutoff established |
| Kultura | First probe around T-15 already lacked a handshake in four runs; no preceding successful observation in those runs |
| Multikino | Readable around T+14; rendered map missing around T+15 in multiple venues |
| Helios | Readable around T+29; rendered map missing around T+30 in two samples |
| Cinema City | Corrected September 17 API probe readable at T+14, explicit TICKETING_ENDED at T+15; earlier DOM failures excluded |
| Bilety24 / Elektronik | Readable at T-1, map unavailable at T in one sample; not evidence for every Bilety24 cinema |
| Kinoteka | Counts readable through T+45; closure not observed |
| Amondo | Corrected September 21 probe returned counts through T+45; earlier parser failures excluded |

Fresh-session validation, safer state classification, event identity validation and production TLS are still required. The roadmap contains provisional future timings; they are not validated production rules.

## Checkpoint

Baseline: 14 existing offline unittest tests passed. The local virtual environment does not currently contain pytest; no dependency installation was performed during this step. The baseline includes experimental behaviors that the roadmap explicitly plans to correct.

After changes: all 14 tests passed again. Additional offline checks confirmed environment-variable loading, zero TMDB requests without a key, cached-poster preservation, and 11 ignore-rule cases (including nested fixtures remaining visible). Git whitespace validation passed. No cinema requests were made.

### September 28 packaging checkpoint

- Python 3.13 is the primary development version; Python 3.12 is also supported. uv 0.12.19 locks runtime/development dependencies, and Hatchling builds the package. The hashed `requirements.txt` export is checked for drift.
- Local validation: 24 tests passed on Windows/Python 3.13; Ruff passed; source scanner reported zero findings; pip-audit reported no known advisories in locked runtime dependencies including optional curl_cffi. A wheel installed/imported successfully in a fresh environment outside the repository.
- Tests prevent external Python socket traffic. Loopback/Unix sockets are allowed for event-loop operation. Seven publisher tests use temporary local repositories and run only on Windows. Browser/cinema behavior still needs the later controlled live validation.
- Removed import-time stdout wrapping so importing the package does not interfere with test capture. Windows UTF-8 configuration remains in the build command entry point.
- GitHub CI covers Linux/Python 3.12 and 3.13 plus Windows/Python 3.13. All three test jobs and the security job passed for commit `600d148`: [run 36439248607](https://github.com/kszat99/warsaw-cinema-aggregator/actions/runs/36439248607). Clean package builds/imports and lock/export consistency passed on each test platform.
- Research scripts/tests are retained as research. Their external Chrome dependency is not yet pinned; the production browser migration/validation remains a later gate.

Remaining owner action: confirm revocation/rotation of the historical TMDB key if live. Phase 0 remains open on that item; the VPS retains its previous checkout/configuration. Existing user review CSV/Markdown and task-registration edits remain outside the packaging commit.
