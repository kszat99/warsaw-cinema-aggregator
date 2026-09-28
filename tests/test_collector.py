import asyncio
import json
import sqlite3
from datetime import date

import pytest
import httpx

from cinema_agg.server.collector import collect
from cinema_agg.server.contracts import LegacyScreening
from cinema_agg.server.database import database_engine, migrate
from cinema_agg.server.importer import import_snapshot
from cinema_agg.server.repository import screenings_page


def row(cinema="example", day="2026-09-29", title="Old"):
    return LegacyScreening(
        cinema_id=cinema,
        cinema_name=cinema,
        title_raw=title,
        title_norm=title.lower(),
        starts_at=f"{day}T20:00:00+02:00",
        scraped_at="2026-09-27T10:00:00+02:00",
        booking_url="https://example.com/book",
    )


def setup(tmp_path, rows=None):
    path = tmp_path / "test.sqlite3"
    migrate(path)
    if rows:
        source = tmp_path / "source.json"
        source.write_text(
            json.dumps(
                {
                    "generated_at": "2026-09-27T10:00:00+02:00",
                    "screenings": [r.model_dump(mode="json") for r in rows],
                }
            )
        )
        import_snapshot(path, source, "Europe/Warsaw")
    return path


def page(path):
    engine = database_engine(path, readonly=True)
    try:
        return screenings_page(engine, limit=200, offset=0)
    finally:
        engine.dispose()


def test_fresh_scope_replaces_only_that_cinema_and_day(tmp_path):
    path = setup(tmp_path, [row(), row(day="2026-09-30"), row(cinema="untouched")])

    async def fetch(cinema, target):
        return [row(title="Fresh")]

    result = asyncio.run(
        collect(path, ["example"], [date(2026, 9, 29)], fetch, delay_seconds=0)
    )
    assert result["status"] == "complete"
    result_page = page(path)
    assert sorted(r.title_raw for r in result_page.screenings) == [
        "Fresh",
        "Old",
        "Old",
    ]
    fresh = next(r for r in result_page.screenings if r.title_raw == "Fresh")
    assert fresh.scraped_at != row().scraped_at
    assert result_page.collection["status"] == "complete"
    assert result_page.collection["snapshot_id"] == result_page.snapshot.id


@pytest.mark.parametrize(
    "failure", ["empty", "exception", "wrong_scope", "drop", "timeout"]
)
def test_bad_scope_keeps_last_good_data(tmp_path, failure):
    path = setup(tmp_path, [row(title=str(i)) for i in range(5)])
    original = page(path)

    async def fetch(cinema, target):
        if failure == "empty":
            return []
        if failure == "exception":
            raise RuntimeError("private diagnostic")
        if failure == "wrong_scope":
            return [row(cinema="wrong")]
        if failure == "timeout":
            await asyncio.sleep(1)
        return [row(title="Too few")]

    result = asyncio.run(
        collect(
            path,
            ["example"],
            [date(2026, 9, 29)],
            fetch,
            delay_seconds=0,
            timeout_seconds=0.01,
        )
    )
    after = page(path)
    assert result["status"] == "failed"
    assert after.snapshot.id == original.snapshot.id
    assert after.screenings == original.screenings
    assert after.collection["status"] == "failed"
    assert "private diagnostic" not in str(after.collection)


def test_partial_run_preserves_failed_day_but_publishes_good_day(tmp_path):
    path = setup(tmp_path, [row(), row(day="2026-09-30")])

    async def fetch(cinema, target):
        if target.day == 30:
            raise TimeoutError()
        return [row(title="Fresh")]

    result = asyncio.run(
        collect(
            path,
            ["example"],
            [date(2026, 9, 29), date(2026, 9, 30)],
            fetch,
            delay_seconds=0,
        )
    )
    assert result["status"] == "partial"
    assert sorted(r.title_raw for r in page(path).screenings) == ["Fresh", "Old"]


def test_failed_first_run_is_visible_without_a_snapshot(tmp_path):
    path = setup(tmp_path)

    async def fetch(cinema, target):
        return []

    asyncio.run(collect(path, ["example"], [date(2026, 9, 29)], fetch, delay_seconds=0))
    response = page(path)
    assert response.snapshot is None
    assert response.collection["status"] == "failed"


def test_cancellation_does_not_publish_and_releases_run_lock(tmp_path):
    path = setup(tmp_path, [row()])
    original = page(path).snapshot.id

    async def fetch(cinema, target):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            collect(path, ["example"], [date(2026, 9, 29)], fetch, delay_seconds=0)
        )
    assert page(path).snapshot.id == original
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT status FROM fetch_runs").fetchone()[0]
            == "interrupted"
        )


def test_concurrent_collector_is_rejected(tmp_path):
    path = setup(tmp_path, [row()])

    async def fetch(cinema, target):
        return [row(title="Fresh")]

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO fetch_runs (id,started_at_ms,status) VALUES ('active',1,'running')"
        )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        asyncio.run(
            collect(path, ["example"], [date(2026, 9, 29)], fetch, delay_seconds=0)
        )
    assert page(path).collection["status"] == "running"


def test_abandoned_run_cannot_publish(tmp_path):
    path = setup(tmp_path, [row()])
    original = page(path).snapshot.id

    async def fetch(cinema, target):
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE fetch_runs SET status='interrupted'")
        return [row(title="Fresh")]

    with pytest.raises(ValueError, match="abandoned"):
        asyncio.run(
            collect(path, ["example"], [date(2026, 9, 29)], fetch, delay_seconds=0)
        )
    assert page(path).snapshot.id == original


def test_changed_snapshot_is_not_overwritten(tmp_path):
    path = setup(tmp_path, [row()])

    async def fetch(cinema, target):
        source = tmp_path / "newer.json"
        source.write_text(
            json.dumps(
                {
                    "generated_at": "2026-09-28T10:00:00+02:00",
                    "screenings": [row(title="Concurrent").model_dump(mode="json")],
                }
            )
        )
        import_snapshot(path, source, "Europe/Warsaw")
        return [row(title="Fresh")]

    with pytest.raises(ValueError, match="changed"):
        asyncio.run(
            collect(path, ["example"], [date(2026, 9, 29)], fetch, delay_seconds=0)
        )
    assert page(path).screenings[0].title_raw == "Concurrent"


def test_explicit_rate_limit_stops_remaining_requests(tmp_path):
    path = setup(tmp_path, [row()])
    calls = []

    async def fetch(cinema, target):
        calls.append(target)
        response = httpx.Response(
            429, request=httpx.Request("GET", "https://example.com")
        )
        raise httpx.HTTPStatusError(
            "limited", request=response.request, response=response
        )

    asyncio.run(
        collect(
            path,
            ["example"],
            [date(2026, 9, 29), date(2026, 9, 30)],
            fetch,
            delay_seconds=0,
        )
    )
    assert len(calls) == 1
    assert [r["outcome"] for r in page(path).collection["results"]] == [
        "blocked",
        "cooldown_skipped",
    ]
