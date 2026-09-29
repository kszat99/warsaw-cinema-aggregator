"""Read-only Kinoteka pilot health report; never calls a cinema or changes jobs."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from .database import database_engine, require_schema
from .settings import Settings

MINUTE = 60_000


def backup_health(folder: Path, now: int) -> dict[str, Any]:
    files = sorted(folder.glob("backup-*.sqlite3"))
    if not files:
        return {"status": "missing", "age_minutes": None}
    latest = files[-1]
    age = (now - int(latest.stat().st_mtime * 1000)) / MINUTE
    try:
        with sqlite3.connect(latest.resolve().as_uri() + "?mode=ro", uri=True) as db:
            valid = db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            db.execute("SELECT id FROM seat_observations LIMIT 0")
    except sqlite3.Error:
        valid = False
    return {
        "status": "invalid" if not valid else "stale" if age > 26 * 60 else "ok",
        "age_minutes": round(age, 1),
        "file": latest.name,
        "scope": "Local backup only; quick_check does not prove offsite recovery",
    }


def report(path: Path, now: int, hours: int = 24) -> dict[str, Any]:
    engine = database_engine(path, readonly=True)
    since = now - hours * 60 * MINUTE
    try:
        with engine.begin() as db:
            require_schema(db)
            worker = dict(
                db.execute(
                    text(
                        "SELECT heartbeat_ms,cooldown_until_ms FROM "
                        "seat_worker_status WHERE id=1"
                    )
                )
                .mappings()
                .one()
            )
            latest = (
                db.execute(
                    text("SELECT * FROM fetch_runs ORDER BY started_at_ms DESC LIMIT 1")
                )
                .mappings()
                .first()
            )
            success = db.execute(
                text(
                    "SELECT max(finished_at_ms) FROM fetch_runs WHERE status='complete'"
                )
            ).scalar()
            scopes = (
                []
                if latest is None
                else [
                    dict(row)
                    for row in db.execute(
                        text(
                            "SELECT "
                            "cinema_id,target_date,outcome,count,"
                            "previous_count,error_type "
                            "FROM fetch_results WHERE run_id=:id ORDER BY "
                            "cinema_id,target_date"
                        ),
                        {"id": latest["id"]},
                    ).mappings()
                ]
            )
            # Window by due time; diagnostics/future jobs never inflate coverage.
            jobs = [
                dict(row)
                for row in db.execute(
                    text(
                        "SELECT j.id,j.state,j.due_at_ms,j.deadline_ms, "
                        "min(CASE WHEN o.outcome='success' THEN "
                        "o.attempted_at_ms END) AS success_at, "
                        "min(o.attempted_at_ms) AS first_attempt "
                        "FROM seat_jobs j LEFT JOIN seat_observations o ON "
                        "o.job_id=j.id "
                        "WHERE j.purpose='scheduled' AND j.due_at_ms BETWEEN "
                        ":since AND :now "
                        "GROUP BY j.id"
                    ),
                    {"since": since, "now": now},
                ).mappings()
            ]
            outcomes = dict(
                db.execute(
                    text(
                        "SELECT o.outcome,count(*) FROM seat_observations o "
                        "JOIN seat_jobs j ON j.id=o.job_id WHERE j.purpose='scheduled' "
                        "AND o.attempted_at_ms BETWEEN :since AND :now GROUP "
                        "BY o.outcome"
                    ),
                    {"since": since, "now": now},
                )
                .tuples()
                .all()
            )
            pending = db.execute(
                text(
                    "SELECT count(*) FROM seat_jobs WHERE state='pending' AND "
                    "due_at_ms>:now"
                ),
                {"now": now},
            ).scalar_one()
            last_finished = db.execute(
                text("SELECT max(finished_at_ms) FROM seat_observations")
            ).scalar()
    finally:
        engine.dispose()
    excluded = {"superseded", "identity_conflict"}
    eligible = [j for j in jobs if j["state"] not in excluded]
    settled = [j for j in eligible if j["deadline_ms"] < now]
    completed = sum(j["success_at"] is not None for j in settled)
    overdue = sum(
        j["state"] in {"pending", "running"} and j["deadline_ms"] < now
        for j in eligible
    )
    delays = [
        max(0, (j["first_attempt"] - j["due_at_ms"]) / 1000)
        for j in eligible
        if j["first_attempt"] is not None
    ]
    heartbeat_age = (
        None
        if worker["heartbeat_ms"] is None
        else (now - worker["heartbeat_ms"]) / 1000
    )
    refresh_age = None if success is None else (now - success) / MINUTE
    backup = backup_health(path.parent / "backups", now)
    issues = []
    if heartbeat_age is None or heartbeat_age > 120:
        issues.append("worker_heartbeat_stale")
    if refresh_age is None or refresh_age > 7 * 60:
        issues.append("schedule_refresh_stale")
    if latest and latest["status"] not in {"complete", "running"}:
        issues.append("latest_refresh_failed_or_partial")
    if (
        latest
        and latest["status"] == "running"
        and now - latest["started_at_ms"] > 10 * MINUTE
    ):
        issues.append("schedule_refresh_stuck")
    if overdue:
        issues.append("overdue_unfinished_jobs")
    if worker["cooldown_until_ms"] > now + MINUTE:
        issues.append("provider_cooldown")
    if backup["status"] != "ok":
        issues.append("backup_" + backup["status"])
    failures = {k: v for k, v in outcomes.items() if k not in {"success", "running"}}
    if failures:
        issues.append("seat_errors_in_window")
    missed = sum(j["state"] == "missed" for j in eligible)
    if missed:
        issues.append("missed_jobs_in_window")
    if any(j["state"] == "identity_conflict" for j in jobs):
        issues.append("screening_identity_conflict")
    if any(j["state"] == "stale_source" for j in eligible):
        issues.append("jobs_with_stale_source")
    return {
        "provider": "kinoteka",
        "generated_at": datetime.fromtimestamp(now / 1000, UTC).isoformat(),
        "window_hours": hours,
        "status": "attention" if issues else "ok",
        "issues": issues,
        "worker": {
            "heartbeat_age_seconds": heartbeat_age,
            "last_finished_at_ms": last_finished,
            "cooldown_until_ms": worker["cooldown_until_ms"],
        },
        "refresh": {
            "last_success_age_minutes": refresh_age,
            "latest": None if latest is None else dict(latest),
            "scopes": scopes,
        },
        "seats": {
            "due": len(eligible),
            "excluded": len(jobs) - len(eligible),
            "windows_finished": len(settled),
            "successful_jobs": completed,
            "coverage_percent": round(100 * completed / len(settled), 1)
            if settled
            else None,
            "missed": missed,
            "overdue_unfinished": overdue,
            "future_pending": pending,
            "max_start_delay_seconds": max(delays) if delays else None,
            "attempt_outcomes": outcomes,
        },
        "backup": backup,
    }


def render(data: dict[str, Any]) -> str:
    refresh, seats, worker, backup = (
        data[k] for k in ("refresh", "seats", "worker", "backup")
    )
    lines = [
        f"KINOTEKA HEALTH: {data['status'].upper()} | last "
        f"{data['window_hours']} hours",
        f"Checked: {data['generated_at']}",
        f"Worker heartbeat age: {worker['heartbeat_age_seconds']} seconds (limit 120)",
        f"Last successful refresh age: {refresh['last_success_age_minutes']} "
        f"minutes (limit 420)",
        f"Seat coverage: "
        f"{seats['successful_jobs']}/{seats['windows_finished']} finished windows "
        f"({seats['coverage_percent']}%); diagnostics excluded",
        f"Missed: {seats['missed']} | overdue unfinished: "
        f"{seats['overdue_unfinished']} | "
        f"future pending: {seats['future_pending']}",
        f"Maximum check start delay: {seats['max_start_delay_seconds']} seconds",
        f"Attempt outcomes: {json.dumps(seats['attempt_outcomes'], sort_keys=True)}",
        f"Local backup: {backup['status']} | age: {backup['age_minutes']} minutes",
        "Refresh cinema/date results (current / previous screening count):",
    ]
    for scope in refresh["scopes"]:
        lines.append(
            f"  {scope['cinema_id']} {scope['target_date']}: {scope['outcome']} "
            f"{scope['count']} / {scope['previous_count']}"
        )
    lines.append("Attention: " + (", ".join(data["issues"]) or "none"))
    lines.append(
        "Missed windows include startup misses; unavailable seats are not "
        "confirmed sales."
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    parser.add_argument(
        "--hours", type=int, choices=range(1, 169), default=24, metavar="1..168"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data = report(
            args.database or Settings.from_environment().database_path,
            int(datetime.now(UTC).timestamp() * 1000),
            args.hours,
        )
    except Exception:
        # No raw exception may expose filesystem or connection details to automation.
        print(json.dumps({"status": "unavailable", "issues": ["health_report_failed"]}))
        raise SystemExit(2) from None
    print(json.dumps(data, indent=2) if args.json else render(data))
    raise SystemExit(1 if data["issues"] else 0)


if __name__ == "__main__":
    main()
