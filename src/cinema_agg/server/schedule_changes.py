"""Reconcile only published, accepted scopes; verify missing bookings off-thread."""

import asyncio
import importlib
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Connection, text

from .database import database_engine

WARSAW = ZoneInfo("Europe/Warsaw")
REFRESH_SPACING_MS = 15 * 60_000


def request_verification(connection: Connection, job: Any, now: int) -> None:
    day = datetime.fromtimestamp(job["starts_at_ms"] / 1000, WARSAW).date().isoformat()
    connection.execute(
        text(
            "INSERT INTO schedule_refresh_requests "
            "(cinema_id,target_date,requested_ms,due_ms,state) "
            "VALUES (:cinema,:day,:now,:now,'pending') "
            "ON CONFLICT(cinema_id,target_date) DO UPDATE SET "
            "requested_ms=:now,due_ms=max(:now,coalesce(started_ms,0)+:spacing),"
            "state='pending',finished_ms=NULL,outcome=NULL "
            "WHERE state='done' AND coalesce(started_ms,0)+:spacing<=:now"
        ),
        {
            "cinema": job["cinema_id"],
            "day": day,
            "now": now,
            "spacing": REFRESH_SPACING_MS,
        },
    )


def reconcile(connection: Connection, run_id: str, snapshot_id: str, now: int) -> int:
    from .seat_pilot import job_identity

    removed = 0
    scopes = (
        connection.execute(
            text(
                "SELECT cinema_id,target_date FROM fetch_results "
                "WHERE run_id=:run AND outcome='accepted'"
            ),
            {"run": run_id},
        )
        .mappings()
        .all()
    )
    for scope in scopes:
        fresh = (
            connection.execute(
                text(
                    "SELECT cinema_id,booking_url,starts_at_ms FROM screenings "
                    "WHERE snapshot_id=:snapshot AND cinema_id=:cinema"
                ),
                {"snapshot": snapshot_id, "cinema": scope["cinema_id"]},
            )
            .mappings()
            .all()
        )
        keys = set()
        trustworthy = True
        for row in fresh:
            day = (
                datetime.fromtimestamp(row["starts_at_ms"] / 1000, WARSAW)
                .date()
                .isoformat()
            )
            if day != scope["target_date"] or row["starts_at_ms"] < now:
                continue
            try:
                cinema, event = job_identity(row["cinema_id"], row["booking_url"] or "")
                keys.add((cinema, event, row["starts_at_ms"]))
            except (ValueError, TypeError):
                trustworthy = False
        if not trustworthy:
            continue
        jobs = (
            connection.execute(
                text(
                    "SELECT * FROM seat_jobs WHERE cinema_id=:cinema "
                    "AND purpose='scheduled' AND starts_at_ms>=:now"
                ),
                {"cinema": scope["cinema_id"], "now": now},
            )
            .mappings()
            .all()
        )
        for job in jobs:
            day = (
                datetime.fromtimestamp(job["starts_at_ms"] / 1000, WARSAW)
                .date()
                .isoformat()
            )
            key = (job["provider_cinema"], job["cinema_event"], job["starts_at_ms"])
            if day != scope["target_date"] or key in keys:
                continue
            connection.execute(
                text(
                    "INSERT INTO schedule_removals VALUES (:job,:run,:now) "
                    "ON CONFLICT(job_id) DO NOTHING"
                ),
                {"job": job["id"], "run": run_id, "now": now},
            )
            connection.execute(
                text(
                    "UPDATE seat_jobs SET state='superseded' WHERE id=:job "
                    "AND state='pending'"
                ),
                {"job": job["id"]},
            )
            removed += 1
        connection.execute(
            text(
                "UPDATE schedule_refresh_requests SET state='done',finished_ms=:now,"
                "outcome='accepted' WHERE cinema_id=:cinema AND target_date=:day"
            ),
            {"now": now, "cinema": scope["cinema_id"], "day": scope["target_date"]},
        )
    return removed


def verify_next(path: Path, now: int) -> bool:
    # Same flock as the regular refresh: never publish overlapping snapshots.
    fcntl = importlib.import_module("fcntl")
    with path.with_suffix(".refresh.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        engine = database_engine(path, readonly=False)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE schedule_refresh_requests SET state='pending' "
                        "WHERE state='running' AND started_ms<:stale"
                    ),
                    {"stale": now - 5 * 60_000},
                )
                last = connection.execute(
                    text("SELECT max(started_ms) FROM schedule_refresh_requests")
                ).scalar()
                if last and last + REFRESH_SPACING_MS > now:
                    return False
                row = (
                    connection.execute(
                        text(
                            "SELECT * FROM schedule_refresh_requests "
                            "WHERE state='pending' "
                            "AND due_ms<=:now ORDER BY requested_ms LIMIT 1"
                        ),
                        {"now": now},
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    return False
                request = dict(row)
                from .seat_providers import PROVIDERS

                cooldown = connection.execute(
                    text(
                        "SELECT cooldown_until_ms FROM seat_provider_status "
                        "WHERE provider=:provider"
                    ),
                    {"provider": PROVIDERS[request["cinema_id"]]},
                ).scalar()
                if cooldown and cooldown > now:
                    return False
                connection.execute(
                    text(
                        "UPDATE schedule_refresh_requests SET state='running',"
                        "started_ms=:now WHERE cinema_id=:cinema AND target_date=:day"
                    ),
                    {
                        "now": now,
                        "cinema": request["cinema_id"],
                        "day": request["target_date"],
                    },
                )
            from .collector import collect, make_fetch, now_ms

            async def fetch_scope() -> dict[str, object]:
                async with httpx.AsyncClient(
                    timeout=30,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as client:
                    return await collect(
                        path,
                        [request["cinema_id"]],
                        [datetime.fromisoformat(request["target_date"]).date()],
                        make_fetch(client),
                    )

            outcome = "verification_failed"
            try:
                result = asyncio.run(fetch_scope())
                outcome = (
                    "accepted" if result["status"] == "complete" else "unconfirmed"
                )
            finally:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE schedule_refresh_requests SET state='done',"
                            "finished_ms=:now,outcome=:outcome "
                            "WHERE cinema_id=:cinema AND target_date=:day"
                        ),
                        {
                            "now": now_ms(),
                            "outcome": outcome,
                            "cinema": request["cinema_id"],
                            "day": request["target_date"],
                        },
                    )
            return True
        finally:
            engine.dispose()
