"""Read-only Kinoteka pilot health report; never calls a cinema or changes jobs."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .database import database_engine, require_schema
from .heartbeat import latest_heartbeat
from .seat_incidents import incidents
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
            seat_incidents = incidents(db, now)
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
                        "SELECT j.id,j.title,j.starts_at_ms,"
                        "j.offset_minutes,j.purpose, "
                        "j.state,j.due_at_ms,j.deadline_ms,j.source_observed_ms, "
                        "min(CASE WHEN o.outcome='success' THEN "
                        "o.attempted_at_ms END) AS success_at, "
                        "min(o.attempted_at_ms) AS first_attempt "
                        "FROM seat_jobs j LEFT JOIN seat_observations o ON "
                        "o.job_id=j.id "
                        "WHERE j.purpose='scheduled' AND j.due_at_ms BETWEEN "
                        ":since AND :now "
                        "GROUP BY j.id ORDER BY j.due_at_ms,j.id"
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
            attempts = [
                dict(row)
                for row in db.execute(
                    text(
                        "SELECT j.id AS job_id,j.title,j.starts_at_ms,"
                        "j.offset_minutes, "
                        "j.purpose,j.state,j.due_at_ms,j.deadline_ms,o.id "
                        "AS attempt_id, "
                        "o.attempted_at_ms,o.finished_at_ms,o.outcome,o.http_status, "
                        "o.available,o.unavailable,o.capacity FROM seat_observations o "
                        "JOIN seat_jobs j ON j.id=o.job_id "
                        "WHERE o.attempted_at_ms BETWEEN :since AND :now "
                        "ORDER BY o.attempted_at_ms DESC,o.id"
                    ),
                    {"since": since, "now": now},
                ).mappings()
            ]
            upcoming = [
                dict(row)
                for row in db.execute(
                    text(
                        "SELECT id,title,starts_at_ms,due_at_ms,offset_minutes,purpose "
                        "FROM seat_jobs WHERE state='pending' AND due_at_ms>:now "
                        "ORDER BY due_at_ms,id LIMIT 3"
                    ),
                    {"now": now},
                ).mappings()
            ]
            last_finished = db.execute(
                text("SELECT max(finished_at_ms) FROM seat_observations")
            ).scalar()
            notifications = [
                dict(row)
                for row in db.execute(
                    text(
                        "SELECT fingerprint,state,last_notified_ms,"
                        "suppress_until_ms,evidence "
                        "FROM alert_state WHERE state IN ('pending_open',"
                        "'pending_resolved') "
                        "OR (state='open' AND last_notified_ms=0) ORDER BY fingerprint"
                    )
                ).mappings()
            ]
            for notification in notifications:
                evidence = json.loads(notification.pop("evidence") or "{}")
                notification["delivery"] = evidence.get("delivery", {})
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
    heartbeat = latest_heartbeat(path)
    issues = []
    if heartbeat and (
        heartbeat["outcome"] != "acknowledged"
        or now - heartbeat["attempted_ms"] > 25 * MINUTE
    ):
        issues.append("external_heartbeat_failed_or_stale")
    if any(not i["recovery"] for i in seat_incidents):
        issues.append("seat_incident_open")
    if notifications:
        issues.append("notification_delivery_pending")
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
        "notifications": notifications,
        "external_heartbeat": heartbeat,
        "seat_incidents": seat_incidents,
        "evidence": {
            "problem_jobs": [
                j
                for j in jobs
                if j["state"] in {"missed", "stale_source", "identity_conflict"}
                or (j["state"] in {"pending", "running"} and j["deadline_ms"] < now)
            ],
            "failed_attempts": [
                a
                for a in attempts
                if a["purpose"] == "scheduled"
                and a["outcome"] not in {"success", "running"}
            ],
            "recent_attempts": attempts[:5],
            "upcoming": upcoming,
        },
        "worker": {
            "heartbeat_age_seconds": heartbeat_age,
            "last_finished_at_ms": last_finished,
            "cooldown_until_ms": worker["cooldown_until_ms"],
        },
        "refresh": {
            "last_success_age_minutes": refresh_age,
            "last_success_at_ms": success,
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


def local_time(value: int | None) -> str:
    if value is None or value == 0:
        return "never recorded"
    return datetime.fromtimestamp(value / 1000, ZoneInfo("Europe/Warsaw")).strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )


def safe_label(value: Any) -> str:
    # Provider strings must not inject terminal escapes or fake report lines.
    return "".join(char if char.isprintable() else " " for char in str(value))


def age(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f}"


def job_lines(job: dict[str, Any], *, attempt: bool = False) -> list[str]:
    purpose = (
        "MANUAL DIAGNOSTIC"
        if job["purpose"] == "diagnostic"
        else (f"scheduled T{job['offset_minutes']:+d} minutes")
    )
    lines = [
        f"  {safe_label(job['title'])}",
        f"    Screening: {local_time(job['starts_at_ms'])} | {purpose}",
        f"    Planned: {local_time(job['due_at_ms'])}",
    ]
    if attempt:
        actual = job["attempted_at_ms"]
        delay = (actual - job["due_at_ms"]) / 1000
        timing = (
            "manual check"
            if job["purpose"] == "diagnostic"
            else (
                "within 120s allowance"
                if actual <= job["deadline_ms"]
                else "OUTSIDE allowance"
            )
        )
        lines.append(
            f"    Attempted: {local_time(actual)} | delay {delay:.1f}s ({timing})"
        )
        lines.append(
            f"    Finished: {local_time(job['finished_at_ms'])} | "
            f"Result: {safe_label(job['outcome'])} | HTTP: {job['http_status']}"
        )
        if job["available"] is not None:
            lines.append(
                f"    Seats: {job['available']} available / "
                f"{job['unavailable']} unavailable / {job['capacity']} capacity"
            )
        else:
            lines.append("    Seats: unknown (no valid counts from this attempt)")
        lines.append(f"    Job: {job['job_id']}")
        lines.append(f"    Attempt ID: {job['attempt_id']}")
    else:
        actual = job.get("first_attempt")
        lines.append(
            "    Attempted: "
            + ("NEVER ATTEMPTED" if actual is None else local_time(actual))
        )
        lines.append(
            f"    State: {job['state']} | Deadline: {local_time(job['deadline_ms'])}"
        )
        if actual is None:
            lines.append(
                "    No seat counts. Why no attempt occurred was not recorded."
            )
        if actual is not None:
            lines.append(
                f"    First attempt delay: {(actual - job['due_at_ms']) / 1000:.1f}s"
            )
        if job["state"] == "stale_source":
            lines.append(
                f"    Source fetched: {local_time(job['source_observed_ms'])} "
                "| maximum source age 48 hours"
            )
        lines.append(f"    Job: {job['id']}")
    return lines


ISSUE_HELP = {
    "external_heartbeat_failed_or_stale": "External heartbeat failed or is older "
    "than 25 minutes. See heartbeat details; inspect cinema-pilot-alerts logs.",
    "seat_incident_open": "A screening has failed checks with no later success "
    "for the same event and start time. See unresolved incidents below.",
    "notification_delivery_pending": "Telegram messages are waiting for delivery. "
    "Delivery details follow; the alert timer retries failures every 15 minutes.",
    "worker_heartbeat_stale": "Worker heartbeat missing or older than 120s. "
    "Check: sudo journalctl -u cinema-seat-pilot -n 30 --no-pager",
    "schedule_refresh_stale": "No complete refresh in 7 hours. "
    "Check: sudo journalctl -u cinema-pilot-refresh -n 30 --no-pager",
    "latest_refresh_failed_or_partial": "Latest refresh did not complete successfully. "
    "See cinema/date outcomes below; retained schedules may be older.",
    "schedule_refresh_stuck": "Refresh has been running for over 10 minutes. "
    "Inspect cinema-pilot-refresh logs.",
    "overdue_unfinished_jobs": "Checks passed their deadline but are unfinished. "
    "Affected jobs follow; inspect worker logs.",
    "provider_cooldown": "Requests paused by provider cooldown until the time below. "
    "Do not repeatedly retry the provider.",
    "backup_missing": "No local backup found. Inspect cinema-pilot-backup logs/timer.",
    "backup_invalid": "Newest local backup failed validation. "
    "Preserve older backups and inspect cinema-pilot-backup logs.",
    "backup_stale": "Newest local backup is over 26 hours old. "
    "Inspect cinema-pilot-backup logs/timer.",
    "seat_errors_in_window": "Scheduled attempts failed in this window. "
    "Each failure follows; these are not proof that ticket sales closed.",
    "missed_jobs_in_window": "Checks missed their allowed window. "
    "Each affected job follows. Historical misses do not prove a current outage.",
    "screening_identity_conflict": "Conflicting start times for a provider event. "
    "Affected jobs follow; validate the source schedule.",
    "jobs_with_stale_source": "Checks were skipped because their source schedule was "
    "too old. Inspect schedule refresh results.",
}


def render(data: dict[str, Any]) -> str:
    refresh, seats, worker, backup = (
        data[k] for k in ("refresh", "seats", "worker", "backup")
    )
    evidence = data["evidence"]
    lines = [
        f"KINOTEKA: {data['status'].upper()} | last {data['window_hours']} hours",
        "All displayed times: Europe/Warsaw. "
        "ATTENTION includes historical problems in this window.",
        "Report generated: "
        + datetime.fromisoformat(data["generated_at"])
        .astimezone(ZoneInfo("Europe/Warsaw"))
        .strftime("%Y-%m-%d %H:%M:%S %Z"),
        "",
        "WHY THIS STATUS",
    ]
    if not data["issues"]:
        lines.append("  No detected problems in the checks below.")
    for issue in data["issues"]:
        lines.append(f"  [{issue}] {ISSUE_HELP[issue]}")
    heartbeat = data.get("external_heartbeat")
    if heartbeat:
        lines.append(
            f"  External heartbeat: {heartbeat['outcome']} | "
            f"attempt {local_time(heartbeat['attempted_ms'])} | "
            f"HTTP {heartbeat['http_status']}"
        )
    else:
        lines.append("  External heartbeat: no local attempts recorded")
    active_incidents = [i for i in data.get("seat_incidents", []) if not i["recovery"]]
    lines.append(f"  Active screening incidents: {len(active_incidents)}")
    for incident in data.get("seat_incidents", []):
        recovery = incident["recovery"]
        if recovery and recovery["attempted_at_ms"] < (
            datetime.fromisoformat(data["generated_at"]).timestamp() * 1000
            - data["window_hours"] * 60 * MINUTE
        ):
            continue
        lines.append(
            f"  {'RECOVERED' if recovery else 'UNRESOLVED'}: "
            f"{safe_label(incident['title'])} | screening "
            f"{local_time(incident['starts_at_ms'])}"
        )
        lines.append("    Failed: " + local_time(incident["first_failure_ms"]))
        lines.append(
            "    Later success: "
            + (local_time(recovery["attempted_at_ms"]) if recovery else "none observed")
        )
    for notification in data.get("notifications", []):
        delivery = notification["delivery"]
        lines.extend(
            [
                f"  Telegram: {notification['fingerprint']} | {notification['state']}",
                f"    Last successful delivery: "
                f"{local_time(notification['last_notified_ms'])}",
                f"    Last try: {local_time(delivery.get('attempted_at_ms'))} | "
                f"error: {delivery.get('error') or 'not recorded'}",
                "    Retry eligible: "
                + (
                    local_time(notification["suppress_until_ms"])
                    if notification["suppress_until_ms"]
                    else "next alert timer run"
                ),
            ]
        )
    if evidence["problem_jobs"]:
        lines.append(
            "\nAFFECTED JOBS (all in window; not hidden by recent-result limit)"
        )
        for job in evidence["problem_jobs"]:
            lines.extend(job_lines(job))
    if evidence["failed_attempts"]:
        lines.append("\nFAILED ATTEMPTS (all in window)")
        for item in evidence["failed_attempts"]:
            lines.extend(job_lines(item, attempt=True))
    lines.extend(
        [
            "\nCURRENT WORKER / REFRESH / BACKUP",
            f"  Heartbeat age: {age(worker['heartbeat_age_seconds'])}s (limit 120s)",
            f"  Last finished attempt: {local_time(worker['last_finished_at_ms'])}",
            f"  Request pacing/cooldown until: "
            f"{local_time(worker['cooldown_until_ms'])}",
            f"  Last complete refresh: {local_time(refresh['last_success_at_ms'])} "
            f"| age {age(refresh['last_success_age_minutes'])}min (limit 420min)",
        ]
    )
    latest = refresh["latest"]
    if latest:
        lines.append(f"  Latest refresh: {latest['status']} | run {latest['id']}")
        lines.append(
            f"    Started: {local_time(latest['started_at_ms'])} | "
            f"Finished: {local_time(latest['finished_at_ms'])}"
        )
    else:
        lines.append("  Latest refresh: none recorded")
    for scope in refresh["scopes"]:
        lines.append(
            f"    {scope['cinema_id']} {scope['target_date']}: "
            f"{scope['outcome']} | screenings {scope['count']} / "
            f"previous {scope['previous_count']} | error "
            f"{scope['error_type'] or 'none'}"
        )
    lines.extend(
        [
            f"  Local backup: {backup['status']} | age {age(backup['age_minutes'])}min "
            "(limit 1560min)",
            f"    File: {backup.get('file', 'none')} | quick_check only; no "
            f"offsite guarantee",
            "\nCOVERAGE (scheduled checks only; diagnostics excluded)",
            f"  {seats['successful_jobs']}/{seats['windows_finished']} "
            f"finished windows "
            f"successful | coverage {age(seats['coverage_percent'])}%",
            f"  Missed: {seats['missed']} | overdue unfinished: "
            f"{seats['overdue_unfinished']} | future pending: "
            f"{seats['future_pending']}",
            f"  Max attempt start delay: {age(seats['max_start_delay_seconds'])}s "
            "| allowance 120s",
            f"  Attempts: {json.dumps(seats['attempt_outcomes'], sort_keys=True)}",
            "\nRECENT ATTEMPTS (latest 5 in window; warnings above include "
            "older failures)",
        ]
    )
    for item in evidence["recent_attempts"]:
        lines.extend(job_lines(item, attempt=True))
    if not evidence["recent_attempts"]:
        lines.append("  No attempts in this window.")
    lines.append("\nNEXT CHECKS (up to 3)")
    for job in evidence["upcoming"]:
        lines.append(
            f"  {local_time(job['due_at_ms'])} | {safe_label(job['title'])} "
            f"| screening {local_time(job['starts_at_ms'])} "
            f"| T{job['offset_minutes']:+d} minutes"
        )
    if not evidence["upcoming"]:
        lines.append("  None pending in the future.")
    lines.append(
        "\nUnavailable seats include holds/blocked seats, not confirmed sales."
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
        print(
            json.dumps({"status": "unavailable", "issues": ["health_report_failed"]})
            if args.json
            else "KINOTEKA: UNAVAILABLE\nCannot read or validate the database/backup. "
            "Check file permissions, configured database path and schema version. "
            "This is a report failure, not evidence that cinema sales closed."
        )
        raise SystemExit(2) from None
    print(json.dumps(data, indent=2) if args.json else render(data))
    raise SystemExit(1 if data["issues"] else 0)


if __name__ == "__main__":
    main()
