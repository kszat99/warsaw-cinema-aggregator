"""Sequential cinema/date collection with durable outcomes and safe publication."""

import argparse
import asyncio
import contextlib
import importlib
import io
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Protocol, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .contracts import LegacyScreening, LegacySnapshot, utc_datetime, utc_milliseconds
from .database import SchemaUnavailable, database_engine, require_schema
from .importer import store_snapshot
from .repository import screenings_page
from .settings import Settings

WARSAW = ZoneInfo("Europe/Warsaw")
Fetch = Callable[[str, date], Awaitable[list[LegacyScreening]]]


class CollectionCooldown(Exception):
    """Do not continue a manual run after an explicit access/rate-limit block."""


def now_ms() -> int:
    return utc_milliseconds(datetime.now(UTC), "UTC")


class QuietOutput(io.TextIOBase):
    def write(self, value: str) -> int:
        # Legacy diagnostics can contain URLs or raw errors. Do not retain them.
        return len(value)


class Cinema(Protocol):
    id: str
    name: str
    url: str
    adapter: str


class LegacyRow(Protocol):
    def model_dump(self) -> dict[str, object]: ...


class Adapter(Protocol):
    def __init__(self, cinema_id: str, cinema_name: str, base_url: str) -> None: ...

    async def fetch_screenings(
        self,
        target_date: date,
        client: httpx.AsyncClient,
    ) -> list[LegacyRow]: ...


def legacy_catalog() -> tuple[dict[str, Cinema], dict[str, type[Adapter]]]:
    # Explicit bridge keeps legacy typing/behavior isolated; no legacy source edits.
    module = importlib.import_module("cinema_agg.build")
    cinemas = cast(list[Cinema], module.CINEMAS)
    return {cinema.id: cinema for cinema in cinemas}, cast(
        dict[str, type[Adapter]],
        module.ADAPTER_MAP,
    )


def make_fetch(client: httpx.AsyncClient) -> Fetch:
    cinemas, adapters = legacy_catalog()
    instances = {
        key: adapters[c.adapter](c.id, c.name, c.url) for key, c in cinemas.items()
    }

    async def fetch(cinema_id: str, target: date) -> list[LegacyScreening]:
        with contextlib.redirect_stdout(QuietOutput()):
            rows = await instances[cinema_id].fetch_screenings(target, client)
        return [LegacyScreening.model_validate(row.model_dump()) for row in rows]

    return fetch


async def collect(
    path: Path,
    cinema_ids: list[str],
    dates: list[date],
    fetch: Fetch,
    *,
    delay_seconds: float = 45,
    timeout_seconds: float = 180,
) -> dict[str, object]:
    if not cinema_ids or not dates or len(set(cinema_ids)) != len(cinema_ids):
        raise ValueError("Nonempty unique cinema scopes are required.")
    if len(set(dates)) != len(dates):
        raise ValueError("Dates must be unique.")
    engine = database_engine(path, readonly=False)
    reader = database_engine(path, readonly=True)
    run_id = uuid4().hex
    started = False
    try:
        baseline = screenings_page(reader, limit=50000, offset=0)
        base_id = baseline.snapshot.id if baseline.snapshot else None
        rows = [
            LegacyScreening.model_validate(row.model_dump(exclude={"id"}))
            for row in baseline.screenings
        ]
        with engine.begin() as connection:
            require_schema(connection)
            connection.execute(
                text(
                    "INSERT INTO fetch_runs (id, started_at_ms, status) "
                    "VALUES (:id, :started, 'running')"
                ),
                {"id": run_id, "started": now_ms()},
            )
        started = True
        accepted = 0
        attempted = 0
        cooldown = False
        for cinema_id in cinema_ids:
            for target in dates:
                if attempted and not cooldown:
                    await asyncio.sleep(delay_seconds)
                attempted += 1
                previous = [
                    row for row in rows if scope_matches(row, cinema_id, target)
                ]
                began = perf_counter()
                count = 0
                error_type = None
                outcome = "fetch_error"
                try:
                    if cooldown:
                        raise CollectionCooldown
                    fresh = await asyncio.wait_for(
                        fetch(cinema_id, target), timeout_seconds
                    )
                    observed = datetime.now(UTC)
                    for row in fresh:
                        if not scope_matches(row, cinema_id, target):
                            raise ValueError(
                                "Adapter returned a different cinema/date."
                            )
                        row.starts_at = utc_datetime(
                            utc_milliseconds(row.starts_at, "Europe/Warsaw")
                        )
                        row.scraped_at = observed
                    count = len(fresh)
                    if not fresh:
                        outcome = "empty_unconfirmed"
                    elif count * 2 < len(previous):
                        outcome = "count_drop_quarantined"
                    else:
                        outcome = "accepted"
                        rows = [
                            row
                            for row in rows
                            if not scope_matches(row, cinema_id, target)
                        ]
                        rows.extend(fresh)
                        accepted += 1
                except CollectionCooldown:
                    outcome = "cooldown_skipped"
                except TimeoutError:
                    outcome = "timeout"
                except httpx.HTTPStatusError as exc:
                    cooldown = exc.response.status_code in {403, 429}
                    outcome = (
                        "blocked"
                        if exc.response.status_code in {403, 429}
                        else "http_error"
                    )
                except Exception as exc:
                    error_type = type(exc).__name__
                result: dict[str, object] = {
                    "run_id": run_id,
                    "cinema_id": cinema_id,
                    "target_date": target.isoformat(),
                    "outcome": outcome,
                    "count": count,
                    "previous_count": len(previous),
                    "duration_ms": int((perf_counter() - began) * 1000),
                    "error_type": error_type,
                    "observed_at_ms": now_ms(),
                }
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO fetch_results (run_id, cinema_id, "
                            "target_date, "
                            "outcome, count, previous_count, duration_ms, error_type, "
                            "observed_at_ms) VALUES (:run_id, :cinema_id, "
                            ":target_date, "
                            ":outcome, :count, :previous_count, :duration_ms, "
                            ":error_type, :observed_at_ms)"
                        ),
                        result,
                    )
                print(json.dumps(result), flush=True)
        status = (
            "complete"
            if accepted == attempted
            else ("partial" if accepted else "failed")
        )
        snapshot_id = None
        with engine.begin() as connection:
            state = connection.execute(
                text("SELECT status FROM fetch_runs WHERE id=:id"), {"id": run_id}
            ).scalar_one()
            if state != "running":
                raise ValueError("Run was abandoned; refusing publication.")
            latest = connection.execute(
                text("SELECT id FROM imports ORDER BY generated_at_ms DESC LIMIT 1")
            ).scalar_one_or_none()
            if latest != base_id:
                raise ValueError(
                    "Snapshot changed during collection; refusing stale publication."
                )
            if accepted:
                data = LegacySnapshot(generated_at=datetime.now(UTC), screenings=rows)
                raw = data.model_dump_json().encode()
                stored = store_snapshot(connection, data, raw, "Europe/Warsaw")
                snapshot_id = stored["snapshot_id"]
            connection.execute(
                text(
                    "UPDATE fetch_runs SET status=:status, finished_at_ms=:finished, "
                    "snapshot_id=:snapshot WHERE id=:id"
                ),
                {
                    "status": status,
                    "finished": now_ms(),
                    "snapshot": snapshot_id,
                    "id": run_id,
                },
            )
        return {
            "run_id": run_id,
            "status": status,
            "accepted_scopes": accepted,
            "attempted_scopes": attempted,
            "snapshot_id": snapshot_id,
        }
    except BaseException:
        if started:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE fetch_runs SET status='interrupted', "
                        "finished_at_ms=:finished "
                        "WHERE id=:id AND status='running'"
                    ),
                    {"id": run_id, "finished": now_ms()},
                )
        raise
    finally:
        engine.dispose()
        reader.dispose()


def scope_matches(row: LegacyScreening, cinema_id: str, target: date) -> bool:
    instant = utc_datetime(utc_milliseconds(row.starts_at, "Europe/Warsaw"))
    return row.cinema_id == cinema_id and instant.astimezone(WARSAW).date() == target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cinema", action="append", required=True, help="ID, repeatable; or all"
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, default=datetime.now(WARSAW).date()
    )
    parser.add_argument("--days", type=int, choices=range(1, 15), default=1)
    args = parser.parse_args()
    cinemas, _ = legacy_catalog()
    selected = list(cinemas) if args.cinema == ["all"] else args.cinema
    if any(key not in cinemas for key in selected) or len(set(selected)) != len(
        selected
    ):
        parser.error("Choose unique configured cinema IDs, or --cinema all.")

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pl-PL,pl;q=0.9"},
        ) as client:
            return await collect(
                Settings.from_environment().database_path,
                selected,
                [args.start + timedelta(days=i) for i in range(args.days)],
                make_fetch(client),
            )

    try:
        result = asyncio.run(run())
    except (SQLAlchemyError, SchemaUnavailable, ValueError):
        print(
            "Collection could not publish. "
            "Check migration, active runs and configuration.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    print(json.dumps(result))
    if result["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
