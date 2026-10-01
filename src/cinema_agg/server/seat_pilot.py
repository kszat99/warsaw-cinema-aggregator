"""Kinoteka and Arkadia background pilot. No seat selection, holds or ticket orders."""

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

from .cinema_city_probe import presentation_id
from .cinema_city_probe import probe as city_probe
from .database import database_engine, require_schema
from .seat_providers import OFFSETS as PROVIDER_OFFSETS
from .seat_providers import (
    PROVIDERS,
    RETRY_BUDGET_MS,
    RETRY_DELAY_MS,
    transport_outcome,
)
from .settings import Settings
from .wisla_probe import event_identity
from .wisla_probe import probe as wisla_probe

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


def job_identity(cinema_id: str, url: str) -> tuple[str, str]:
    if cinema_id == "wisla":
        return "wisla", event_identity(url)
    if cinema_id == "1074":
        return "1074", presentation_id(url)
    if cinema_id == "kinoteka":
        return booking_identity(url)
    raise ValueError("Cinema not enabled")


def plan(
    engine: Engine, now: int, *, diagnostic: bool = False, cinema_id: str | None = None
) -> int:
    """Stable provider ID + start/revision + offset deduplicates repeated planning."""
    inserted = 0
    with engine.begin() as connection:
        require_schema(connection)
        # Retire only unattempted obsolete timings; preserve attempts and history.
        connection.execute(
            text(
                "UPDATE seat_jobs SET state='superseded' WHERE provider='msi_wisla' "
                "AND purpose='scheduled' AND offset_minutes IN (0,5) "
                "AND state='pending' AND retry_at_ms IS NULL"
            )
        )
        rows = (
            connection.execute(
                text(
                    "SELECT cinema_id, booking_url, title_raw, "
                    "starts_at_ms, scraped_at_ms FROM "
                    "screenings "
                    "WHERE snapshot_id=(SELECT id FROM imports ORDER BY "
                    "generated_at_ms DESC LIMIT 1) "
                    "AND cinema_id IN ('kinoteka','1074','wisla') AND "
                    "(:cinema_id IS NULL OR cinema_id=:cinema_id) "
                    "AND starts_at_ms >= :oldest "
                    "AND starts_at_ms <= :horizon AND scraped_at_ms >= :fresh "
                    "ORDER BY starts_at_ms, ordinal"
                ),
                {
                    "cinema_id": cinema_id,
                    "oldest": now + 5 * MINUTE if diagnostic else now - 42 * MINUTE,
                    "horizon": now + FRESHNESS,
                    "fresh": now - FRESHNESS,
                },
            )
            .mappings()
            .all()
        )
        for provider in {PROVIDERS[row["cinema_id"]] for row in rows}:
            connection.execute(
                text(
                    "INSERT INTO seat_provider_status(provider,cooldown_until_ms) "
                    "VALUES (:provider,0) ON CONFLICT(provider) DO NOTHING"
                ),
                {"provider": provider},
            )
            connection.execute(
                text(
                    "UPDATE seat_provider_status SET activated_at_ms=:now "
                    "WHERE provider=:provider AND activated_at_ms IS NULL"
                ),
                {"provider": provider, "now": now},
            )
        activation = dict(
            connection.execute(
                text("SELECT provider,activated_at_ms FROM seat_provider_status")
            )
            .tuples()
            .all()
        )
        starts_by_event: dict[tuple[str, str], set[int]] = {}
        for row in rows:
            try:
                key = job_identity(row["cinema_id"], row["booking_url"] or "")
            except (ValueError, TypeError):
                continue
            starts_by_event.setdefault(key, set()).add(row["starts_at_ms"])
        for row in rows:
            try:
                cinema, event_id = job_identity(
                    row["cinema_id"], row["booking_url"] or ""
                )
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
            provider = PROVIDERS[row["cinema_id"]]
            for offset in (0,) if diagnostic else PROVIDER_OFFSETS[provider]:
                purpose = "diagnostic" if diagnostic else "scheduled"
                identity = (
                    f"{provider}:{cinema}:{event_id}:{row['starts_at_ms']}:{offset}:v1"
                )
                if diagnostic:
                    identity += ":" + uuid4().hex
                job_id = hashlib.sha256(identity.encode()).hexdigest()
                due = now if diagnostic else row["starts_at_ms"] + offset * MINUTE
                # Spread early snapshots reproducibly; keep near-start checks exact.
                if not diagnostic and offset <= -30:
                    due += int(job_id[:8], 16) % 60_000
                if due < activation[provider]:
                    continue
                if (
                    not diagnostic
                    and due < now
                    and not connection.execute(
                        text("SELECT 1 FROM seat_jobs WHERE id=:id"), {"id": job_id}
                    ).scalar()
                ):
                    continue
                deadline = due + 2 * MINUTE
                if provider == "msi_wisla" and offset == -2 and not diagnostic:
                    deadline = row["starts_at_ms"] - 1
                result = connection.execute(
                    text(
                        "INSERT INTO seat_jobs (id, provider, cinema_id, "
                        "cinema_event, provider_cinema, "
                        "title, "
                        "starts_at_ms, source_observed_ms, offset_minutes, purpose, "
                        "due_at_ms, deadline_ms, state) VALUES "
                        "(:id, :provider, :catalog, :event, :cinema, "
                        ":title, :start, :observed, :offset, "
                        ":purpose, "
                        ":due, :deadline, :state) ON CONFLICT(id) DO UPDATE SET "
                        "source_observed_ms=excluded.source_observed_ms, "
                        "title=excluded.title"
                    ),
                    {
                        "id": job_id,
                        "provider": provider,
                        "catalog": row["cinema_id"],
                        "event": event_id,
                        "cinema": cinema,
                        "title": row["title_raw"],
                        "start": row["starts_at_ms"],
                        "observed": row["scraped_at_ms"],
                        "offset": offset,
                        "purpose": purpose,
                        "due": due,
                        "deadline": deadline,
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
        # Optional final Wisla check needs a minute for its fresh-session flow.
        connection.execute(
            text(
                "UPDATE seat_jobs SET state='cutoff_skipped' WHERE state='pending' "
                "AND provider='msi_wisla' AND purpose='scheduled' "
                "AND offset_minutes=-2 AND starts_at_ms <= :limit"
            ),
            {"limit": now + MINUTE},
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
                "UPDATE seat_jobs SET state='done' WHERE state='pending' "
                "AND retry_at_ms IS NOT NULL AND deadline_ms < :now + "
                "CASE provider WHEN 'cinema_city' THEN :city "
                "WHEN 'msi_wisla' THEN :wisla ELSE :kinoteka END"
            ),
            {
                "now": now,
                "city": RETRY_BUDGET_MS["cinema_city"],
                "wisla": RETRY_BUDGET_MS["msi_wisla"],
                "kinoteka": RETRY_BUDGET_MS["kinoteka"],
            },
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
                    "AND (retry_at_ms IS NULL OR retry_at_ms<=:now) "
                    "AND (:diagnostic=0 OR purpose='diagnostic') "
                    "AND provider IN (SELECT provider FROM seat_provider_status "
                    "WHERE cooldown_until_ms<=:now) "
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
    if job.get("provider") == "msi_wisla":
        if job.get("cinema_id") != "wisla" or job["provider_cinema"] != "wisla":
            raise ValueError("Invalid Wisla cinema")
        final = job.get("purpose") == "scheduled" and job.get("offset_minutes") == -2
        return wisla_probe(
            client,
            str(job["cinema_event"]),
            job["starts_at_ms"],
            finish_before_ms=job["starts_at_ms"] if final else None,
        )
    if job.get("provider", "kinoteka") == "cinema_city":
        empty = {
            "available": None,
            "unavailable": None,
            "capacity": None,
            "http_status": None,
            "cooldown_ms": 0,
        }
        event = str(job["cinema_event"])
        if (
            job.get("cinema_id") != "1074"
            or job["provider_cinema"] != "1074"
            or not event.isdigit()
        ):
            return {**empty, "outcome": "invalid_data"}
        city_result = city_probe(
            client, f"https://tickets.cinema-city.pl/order/{event}"
        )
        return {
            **empty,
            **city_result,
            "cooldown_ms": max(15 * MINUTE, city_result.get("cooldown_ms", 0))
            if city_result["outcome"] == "blocked"
            else 0,
        }
    if job.get("provider", "kinoteka") != "kinoteka":
        raise ValueError("Unknown seat provider")
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
    except httpx.HTTPError as error:
        result["outcome"] = transport_outcome(error)
    except (ValueError, AttributeError, TypeError):
        result["outcome"] = "invalid_data"
    return result


def finish(
    engine: Engine, job: Mapping[str, Any], result: dict[str, Any], now: int
) -> bool:
    with engine.begin() as connection:
        # Read durable state, never trust an old caller's view when consuming budget.
        current = (
            connection.execute(
                text(
                    "SELECT * FROM seat_jobs WHERE id=:id AND state='running' "
                    "AND claim_token=:token AND lease_until_ms>=:now"
                ),
                {"id": job["id"], "token": job["claim_token"], "now": now},
            )
            .mappings()
            .first()
        )
        if current is None:
            return False
        attempts = connection.execute(
            text("SELECT count(*) FROM seat_observations WHERE job_id=:id"),
            {"id": job["id"]},
        ).scalar_one()
        if (current["retry_at_ms"] is not None and now > current["deadline_ms"]) or (
            current["provider"] == "msi_wisla"
            and current["purpose"] == "scheduled"
            and current["offset_minutes"] == -2
            and now >= current["starts_at_ms"]
        ):
            # A slow response is retained as a late attempt, not on-time coverage.
            result.update(
                outcome="deadline_exceeded",
                available=None,
                unavailable=None,
                capacity=None,
            )
        retry_at = now + RETRY_DELAY_MS
        retry = (
            current["purpose"] == "scheduled"
            and current["retry_at_ms"] is None
            and attempts == 1
            and result["outcome"] in {"network_error", "timeout"}
            and not result["cooldown_ms"]
            and retry_at + RETRY_BUDGET_MS[current["provider"]]
            <= current["deadline_ms"]
        )
        result["retry_scheduled"] = retry
        result["retry_at_ms"] = retry_at if retry else current["retry_at_ms"]
        updated = connection.execute(
            text(
                "UPDATE seat_jobs SET state=:state, lease_until_ms=NULL, "
                "retry_at_ms=:retry_at WHERE id=:id "
                "AND state='running' AND claim_token=:token AND lease_until_ms >= :now"
            ),
            {
                "id": job["id"],
                "token": job["claim_token"],
                "now": now,
                "state": "pending" if retry else "done",
                "retry_at": retry_at if retry else current["retry_at_ms"],
            },
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
            {"now": now, "cooldown": now + 2000},
        )
        connection.execute(
            text(
                "UPDATE seat_provider_status SET "
                "cooldown_until_ms=max(cooldown_until_ms,:until) "
                "WHERE provider=:provider"
            ),
            {"until": now + result["cooldown_ms"], "provider": job["provider"]},
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
                    "SELECT j.provider,j.cinema_id,j.title,"
                    "j.starts_at_ms,j.offset_minutes,j.purpose,o.* "
                    "FROM seat_observations o JOIN seat_jobs j ON j.id=o.job_id "
                    "ORDER BY o.attempted_at_ms DESC LIMIT 5"
                )
            )
            .mappings()
            .all()
        )
        return {
            "providers": list(PROVIDER_OFFSETS),
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
    parser.add_argument(
        "--cinema", choices=list(PROVIDERS), help="Diagnostic target only"
    )
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
                        "j.provider,j.cinema_id,j.cinema_event,j.title,"
                        "j.starts_at_ms,j.offset_minutes,j.purpose,"
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
        plan(engine, clock_ms(), diagnostic=diagnostic, cinema_id=args.cinema)
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
                                "provider": job["provider"],
                                "cinema_id": job["cinema_id"],
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
