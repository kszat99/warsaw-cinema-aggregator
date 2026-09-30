"""Derive screening-specific failure episodes without discarding observations."""

from typing import Any

from sqlalchemy import Connection, text

from .seat_providers import cinema_name


def incidents(connection: Connection, now: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            "SELECT j.provider,j.cinema_id,j.provider_cinema,"
            "j.cinema_event,j.starts_at_ms,j.title,"
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
    active: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["provider"],
            row["provider_cinema"],
            row["cinema_event"],
            row["starts_at_ms"],
        )
        if row["outcome"] == "success":
            incident = active.pop(key, None)
            if incident is not None:
                incident["recovery"] = dict(row)
            continue
        if row["outcome"] == "closed":
            continue  # Explicit sales closure is not a transport failure or recovery.
        if key not in active:
            incident = {
                "fingerprint": "seat:" + row["id"],
                "title": row["title"],
                "cinema_id": row["cinema_id"],
                "provider": row["provider"],
                "starts_at_ms": row["starts_at_ms"],
                "first_failure_ms": row["attempted_at_ms"],
                "last_failure_ms": row["attempted_at_ms"],
                "last_outcome": row["outcome"],
                "failures": 0,
                "failed_attempt_ids": [],
                "failed_job_ids": [],
                "recovery": None,
            }
            active[key] = incident
            result.append(incident)
        active[key]["failures"] += 1
        active[key]["failed_attempt_ids"].append(row["id"])
        active[key]["failed_job_ids"].append(row["job_id"])
        active[key]["last_failure_ms"] = row["attempted_at_ms"]
        active[key]["last_outcome"] = row["outcome"]
    return result


def incident_message(incident: dict[str, Any]) -> str:
    from .pilot_health import local_time, safe_label

    recovery = incident["recovery"]
    headline = "RECOVERED: seat checks" if recovery else "SEAT CHECK FAILED"
    lines = [
        headline,
        cinema_name(incident.get("cinema_id", "kinoteka")),
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
                (
                    "Same scheduled window recovered via retry; "
                    "failed attempt retained."
                    if recovery["job_id"] in incident["failed_job_ids"]
                    else "The failed snapshot remains missing; "
                    "later success resolves the incident."
                ),
                "If no earlier alert arrived, this is the "
                "combined failure/recovery summary.",
            ]
        )
    else:
        lines.append("No later successful check for this screening has been observed.")
    lines.append("Details: sudo cinema-pilot-status")
    return "\n".join(lines)
