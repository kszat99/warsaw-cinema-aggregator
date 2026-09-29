"""Derive screening-specific failure episodes without discarding observations."""

from typing import Any

from sqlalchemy import Connection, text


def incidents(connection: Connection, now: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            "SELECT j.provider_cinema,j.cinema_event,j.starts_at_ms,j.title,"
            "j.id AS job_id,j.offset_minutes,"
            "o.id,o.attempted_at_ms,o.finished_at_ms,o.outcome,o.available,"
            "o.unavailable,o.capacity FROM seat_observations o "
            "JOIN seat_jobs j ON j.id=o.job_id WHERE j.purpose='scheduled' "
            "AND o.outcome!='running' AND o.attempted_at_ms<=:now "
            "ORDER BY o.attempted_at_ms,o.id"
        ),
        {"now": now},
    ).mappings()
    result: list[dict[str, Any]] = []
    active: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["provider_cinema"], row["cinema_event"], row["starts_at_ms"])
        if row["outcome"] == "success":
            incident = active.pop(key, None)
            if incident is not None:
                incident["recovery"] = dict(row)
            continue
        if key not in active:
            incident = {
                "fingerprint": "seat:" + row["id"],
                "title": row["title"],
                "starts_at_ms": row["starts_at_ms"],
                "first_failure_ms": row["attempted_at_ms"],
                "last_failure_ms": row["attempted_at_ms"],
                "last_outcome": row["outcome"],
                "failures": 0,
                "failed_attempt_ids": [],
                "recovery": None,
            }
            active[key] = incident
            result.append(incident)
        active[key]["failures"] += 1
        active[key]["failed_attempt_ids"].append(row["id"])
        active[key]["last_failure_ms"] = row["attempted_at_ms"]
        active[key]["last_outcome"] = row["outcome"]
    return result


def incident_message(incident: dict[str, Any]) -> str:
    from .pilot_health import local_time, safe_label

    recovery = incident["recovery"]
    headline = "RECOVERED: seat checks" if recovery else "SEAT CHECK FAILED"
    lines = [
        headline,
        safe_label(incident["title"])[:180],
        "Screening: " + local_time(incident["starts_at_ms"]),
        "First failed attempt: " + local_time(incident["first_failure_ms"]),
        f"Failed attempts: {incident['failures']} | {incident['last_outcome']}",
    ]
    if recovery:
        lines.extend(
            [
                "Later successful check: " + local_time(recovery["attempted_at_ms"]),
                f"Seats: {recovery['available']} available / "
                f"{recovery['unavailable']} unavailable / "
                f"{recovery['capacity']} capacity",
                "The failed snapshot remains missing; "
                "later success resolves the incident.",
                "If no earlier alert arrived, this is the "
                "combined failure/recovery summary.",
            ]
        )
    else:
        lines.append("No later successful check for this screening has been observed.")
    lines.append("Details: sudo cinema-pilot-status")
    return "\n".join(lines)
