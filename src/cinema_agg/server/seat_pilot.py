"""Kinoteka-only background pilot. No seat selection, holds or ticket orders."""

import argparse
import csv
import hashlib
import json
import signal
import sqlite3
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import Engine, text

from .database import database_engine, require_schema
from .settings import Settings

OFFSETS = (-5, 0, 5, 40)
MINUTE = 60000
FRESHNESS = 48 * 60 * MINUTE


def clock_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def booking_identity(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "bilety.kinoteka.pl":
        raise ValueError("Unapproved booking origin")
    query = parts.query or parts.fragment.partition("?")[2]
    values = parse_qs(query)
    if len(values.get("cinemaId", [])) != 1 or len(values.get("screeningId", [])) != 1:
        raise ValueError("Missing or ambiguous provider identity")
    return str(UUID(values["cinemaId"][0])), str(UUID(values["screeningId"][0]))


def plan(engine: Engine, now: int, *, diagnostic: bool = False) -> int:
    """Stable provider ID + start/revision + offset deduplicates repeated planning."""
    inserted = 0
    with engine.begin() as connection:
        require_schema(connection)
        rows = (
            connection.execute(
                text(
                    "SELECT booking_url, title_raw, starts_at_ms, scraped_at_ms FROM "
                    "screenings "
                    "WHERE snapshot_id=(SELECT id FROM imports ORDER BY "
                    "generated_at_ms DESC LIMIT 1) "
                    "AND cinema_id='kinoteka' AND starts_at_ms >= :oldest "
                    "AND starts_at_ms <= :horizon AND scraped_at_ms >= :fresh "
                    "ORDER BY starts_at_ms, ordinal"
                ),
                {
                    "oldest": now + 5 * MINUTE if diagnostic else now - 42 * MINUTE,
                    "horizon": now + FRESHNESS,
                    "fresh": now - FRESHNESS,
                },
            )
            .mappings()
            .all()
        )
        starts_by_event: dict[tuple[str, str], set[int]] = {}
        for row in rows:
            try:
                key = booking_identity(row["booking_url"] or "")
            except (ValueError, TypeError):
                continue
            starts_by_event.setdefault(key, set()).add(row["starts_at_ms"])
        for row in rows:
            try:
                cinema, event_id = booking_identity(row["booking_url"] or "")
            except (ValueError, TypeError):
                continue
            if len(starts_by_event[(cinema, event_id)]) != 1:
                connection.execute(
                    text(
                        "UPDATE seat_jobs SET state='identity_conflict' "
                        "WHERE provider_cinema=:cinema AND cinema_event=:event "
                        "AND state='pending'"
                    ),
                    {"cinema": cinema, "event": event_id},
                )
                continue
            # A reschedule supersedes pending old timings, retaining all observations.
            connection.execute(
                text(
                    "UPDATE seat_jobs SET state='superseded' WHERE cinema_event=:event "
                    "AND provider_cinema=:cinema AND starts_at_ms != :start AND "
                    "state='pending'"
                ),
                {"event": event_id, "cinema": cinema, "start": row["starts_at_ms"]},
            )
            for offset in (0,) if diagnostic else sorted(set(OFFSETS)):
                purpose = "diagnostic" if diagnostic else "scheduled"
                identity = (
                    f"kinoteka:{cinema}:{event_id}:{row['starts_at_ms']}:{offset}:v1"
                )
                if diagnostic:
                    identity += ":" + uuid4().hex
                job_id = hashlib.sha256(identity.encode()).hexdigest()
                due = now if diagnostic else row["starts_at_ms"] + offset * MINUTE
                result = connection.execute(
                    text(
                        "INSERT INTO seat_jobs (id, cinema_event, provider_cinema, "
                        "title, "
                        "starts_at_ms, source_observed_ms, offset_minutes, purpose, "
                        "due_at_ms, deadline_ms, state) VALUES "
                        "(:id, :event, :cinema, :title, :start, :observed, :offset, "
                        ":purpose, "
                        ":due, :deadline, :state) ON CONFLICT(id) DO UPDATE SET "
                        "source_observed_ms=excluded.source_observed_ms, "
                        "title=excluded.title"
                    ),
                    {
                        "id": job_id,
                        "event": event_id,
                        "cinema": cinema,
                        "title": row["title_raw"],
                        "start": row["starts_at_ms"],
                        "observed": row["scraped_at_ms"],
                        "offset": offset,
                        "purpose": purpose,
                        "due": due,
                        "deadline": due + 2 * MINUTE,
                        "state": "missed" if due + 2 * MINUTE < now else "pending",
                    },
                )
                inserted += result.rowcount
            if diagnostic:
                break
    return inserted


def claim(
    engine: Engine,
    now: int,
    *,
    diagnostic_only: bool = False,
) -> Mapping[str, Any] | None:
    with engine.begin() as connection:
        require_schema(connection)
        connection.execute(
            text("UPDATE seat_worker_status SET heartbeat_ms=:now WHERE id=1"),
            {"now": now},
        )
        # Expired attempts remain visible, and may be retried only inside their window.
        connection.execute(
            text(
                "UPDATE seat_observations SET outcome='interrupted', "
                "finished_at_ms=:now "
                "WHERE outcome='running' AND id IN (SELECT claim_token FROM seat_jobs "
                "WHERE state='running' AND lease_until_ms < :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "UPDATE seat_jobs SET state='pending', claim_token=NULL, "
                "lease_until_ms=NULL "
                "WHERE state='running' AND lease_until_ms < :now"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "UPDATE seat_jobs SET state='missed' WHERE state='pending' AND "
                "deadline_ms < :now"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "UPDATE seat_jobs SET state='stale_source' WHERE state='pending' "
                "AND due_at_ms <= :now AND source_observed_ms < :fresh"
            ),
            {"now": now, "fresh": now - FRESHNESS},
        )
        blocked = connection.execute(
            text("SELECT cooldown_until_ms FROM seat_worker_status WHERE id=1")
        ).scalar_one()
        if (
            blocked > now
            or connection.execute(
                text("SELECT count(*) FROM seat_jobs WHERE state='running'")
            ).scalar_one()
        ):
            return None
        row = (
            connection.execute(
                text(
                    "SELECT * FROM seat_jobs WHERE state='pending' AND due_at_ms <= "
                    ":now "
                    "AND (:diagnostic=0 OR purpose='diagnostic') "
                    "ORDER BY deadline_ms, id LIMIT 1"
                ),
                {"now": now, "diagnostic": int(diagnostic_only)},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        token = uuid4().hex
        connection.execute(
            text(
                "UPDATE seat_jobs SET state='running', claim_token=:token, "
                "lease_until_ms=:lease "
                "WHERE id=:id"
            ),
            {"token": token, "lease": now + 2 * MINUTE, "id": row["id"]},
        )
        connection.execute(
            text(
                "INSERT INTO seat_observations (id,job_id,attempted_at_ms,outcome) "
                "VALUES (:token,:id,:now,'running')"
            ),
            {"token": token, "id": row["id"], "now": now},
        )
        return {**dict(row), "claim_token": token}


def probe(client: httpx.Client, job: Mapping[str, Any]) -> dict[str, Any]:
    # Validate again at the network boundary, even if the database was modified.
    cinema, event_id = str(UUID(job["provider_cinema"])), str(UUID(job["cinema_event"]))
    url = f"https://restapi.kinoteka.pl/api/cinema/{cinema}/screening/{event_id}/occupancy"
    result: dict[str, Any] = {
        "outcome": "network_error",
        "available": None,
        "unavailable": None,
        "capacity": None,
        "http_status": None,
        "cooldown_ms": 0,
    }
    try:
        response = client.get(url, follow_redirects=False)
        result["http_status"] = response.status_code
        if response.status_code in {403, 429}:
            result["outcome"] = "blocked"
            result["cooldown_ms"] = 15 * MINUTE
            retry = response.headers.get("Retry-After", "")
            if retry.isdigit():
                result["cooldown_ms"] = max(15 * MINUTE, min(int(retry), 86400) * 1000)
            return result
        if response.status_code != 200:
            result["outcome"] = "upstream_error"  # 404 is NOT confirmed sales closure.
            return result
        data = response.json()
        available, unavailable = data.get("seatsLeft"), data.get("totalOccupied")
        if (
            type(available) is not int
            or type(unavailable) is not int
            or available < 0
            or unavailable < 0
            or not 0 < available + unavailable <= 5000
        ):
            raise ValueError("Untrusted seat counts")
        result.update(
            outcome="success",
            available=available,
            unavailable=unavailable,
            capacity=available + unavailable,
        )
    except httpx.TimeoutException:
        result["outcome"] = "timeout"
    except httpx.HTTPError:
        result["outcome"] = "network_error"
    except (ValueError, AttributeError, TypeError):
        result["outcome"] = "invalid_data"
    return result


def finish(
    engine: Engine, job: Mapping[str, Any], result: dict[str, Any], now: int
) -> bool:
    with engine.begin() as connection:
        updated = connection.execute(
            text(
                "UPDATE seat_jobs SET state='done', lease_until_ms=NULL WHERE id=:id "
                "AND state='running' AND claim_token=:token AND lease_until_ms >= :now"
            ),
            {"id": job["id"], "token": job["claim_token"], "now": now},
        )
        if not updated.rowcount:
            return False
        connection.execute(
            text(
                "UPDATE seat_observations SET finished_at_ms=:now,outcome=:outcome,"
                "available=:available,unavailable=:unavailable,capacity=:capacity,"
                "http_status=:http_status WHERE id=:token"
            ),
            {**result, "now": now, "token": job["claim_token"]},
        )
        connection.execute(
            text(
                "UPDATE seat_worker_status SET heartbeat_ms=:now, "
                "cooldown_until_ms=max(cooldown_until_ms,:cooldown) WHERE id=1"
            ),
            {"now": now, "cooldown": now + max(2000, result["cooldown_ms"])},
        )
        return True


def status(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        require_schema(connection)
        worker = dict(
            connection.execute(text("SELECT * FROM seat_worker_status WHERE id=1"))
            .mappings()
            .one()
        )
        jobs = dict(
            connection.execute(
                text("SELECT state,count(*) FROM seat_jobs GROUP BY state")
            )
            .tuples()
            .all()
        )
        outcomes = dict(
            connection.execute(
                text("SELECT outcome,count(*) FROM seat_observations GROUP BY outcome")
            )
            .tuples()
            .all()
        )
        next_due = connection.execute(
            text("SELECT min(due_at_ms) FROM seat_jobs WHERE state='pending'")
        ).scalar()
        latest = (
            connection.execute(
                text(
                    "SELECT j.title,j.starts_at_ms,j.offset_minutes,j.purpose,o.* "
                    "FROM seat_observations o JOIN seat_jobs j ON j.id=o.job_id "
                    "ORDER BY o.attempted_at_ms DESC LIMIT 5"
                )
            )
            .mappings()
            .all()
        )
        return {
            "provider": "kinoteka",
            "worker": worker,
            "jobs": jobs,
            "outcomes": outcomes,
            "next_due_ms": next_due,
            "latest": [dict(row) for row in latest],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument(
        "command", choices=["run", "status", "probe-next", "export", "backup"]
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = args.database or Settings.from_environment().database_path
    if args.command == "backup":
        if args.output is None:
            folder = path.parent / "backups"
            folder.mkdir(exist_ok=True)
            args.output = folder / datetime.now(UTC).strftime(
                "backup-%Y%m%dT%H%M%S.sqlite3"
            )
        if args.output.exists():
            parser.error("backup requires a new output path")
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(args.output) as dest:
                source.backup(dest)
                if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Backup integrity check failed")
        print("SQLite backup completed and integrity checked.", flush=True)
        return
    engine = database_engine(path, readonly=args.command in {"status", "export"})
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    try:
        if args.command == "status":
            print(json.dumps(status(engine), ensure_ascii=True, indent=2))
            return
        if args.command == "export":
            if args.output is None:
                parser.error("export requires --output")
            with (
                engine.connect() as connection,
                args.output.open("x", newline="", encoding="utf-8") as handle,
            ):
                rows = connection.execute(
                    text(
                        "SELECT "
                        "j.cinema_event,j.title,j.starts_at_ms,j.offset_minutes,j.purpose,"
                        "o.* FROM seat_observations o JOIN seat_jobs j ON "
                        "j.id=o.job_id "
                        "ORDER BY o.attempted_at_ms"
                    )
                )
                writer = csv.writer(handle)
                writer.writerow(rows.keys())
                for row in rows:
                    writer.writerow(
                        [
                            "'" + value
                            if isinstance(value, str)
                            and value.lstrip().startswith(("=", "+", "-", "@"))
                            else value
                            for value in row
                        ]
                    )
            return
        diagnostic = args.command == "probe-next"
        plan(engine, clock_ms(), diagnostic=diagnostic)
        last_plan = clock_ms()
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            while not stop.is_set():
                now = clock_ms()
                if not diagnostic and now - last_plan >= MINUTE:
                    plan(engine, now)
                    last_plan = now
                job = claim(engine, now, diagnostic_only=diagnostic)
                if job:
                    result = probe(client, job)
                    saved = finish(engine, job, result, clock_ms())
                    print(
                        json.dumps(
                            {
                                "event": "seat_observation",
                                "job_id": job["id"],
                                "saved": saved,
                                **result,
                            }
                        ),
                        flush=True,
                    )
                if diagnostic:
                    if job is None:
                        print(
                            "No claimable job: check schedules, freshness or cooldown."
                        )
                        raise SystemExit(1)
                    if result["outcome"] != "success":
                        raise SystemExit(1)
                    return
                stop.wait(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
