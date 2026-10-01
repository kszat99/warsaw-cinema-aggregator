"""Derive screening-specific failure episodes without discarding observations."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from .schedule_changes import WARSAW
from .seat_providers import EXPECTED_CUTOFF_OUTCOMES, cinema_name


def incidents(connection: Connection, now: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            "SELECT j.provider,j.cinema_id,j.provider_cinema,"
            "j.cinema_event,j.starts_at_ms,j.title,"
            "j.id AS job_id,j.offset_minutes,"
            "o.id,o.attempted_at_ms,o.finished_at_ms,o.outcome,o.available,"
            "o.unavailable,o.capacity,o.http_status,o.diagnostics_json "
            "FROM seat_observations o "
            "JOIN seat_jobs j ON j.id=o.job_id WHERE j.purpose='scheduled' "
            "AND o.outcome!='running' AND o.attempted_at_ms<=:now "
            "ORDER BY o.attempted_at_ms,o.id"
        ),
        {"now": now},
    ).mappings()
    result: list[dict[str, Any]] = []
    active: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    last_success: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["provider"],
            row["provider_cinema"],
            row["cinema_event"],
            row["starts_at_ms"],
        )
        if row["outcome"] == "success":
            last_success[key] = dict(row)
            incident = active.pop(key, None)
            if incident is not None:
                incident["recovery"] = dict(row)
            continue
        if row["outcome"] == "closed":
            continue  # Explicit sales closure is not a transport failure or recovery.
        prior = last_success.get(key)
        expected = (
            row["outcome"] in EXPECTED_CUTOFF_OUTCOMES.get(row["provider"], set())
            and row["offset_minutes"] >= 0
            and row["attempted_at_ms"] >= row["starts_at_ms"]
            and prior is not None
            and prior["offset_minutes"] in {-5, -2}
            and prior["attempted_at_ms"] < row["starts_at_ms"]
            and prior["finished_at_ms"] is not None
            and prior["finished_at_ms"] < row["starts_at_ms"]
        )
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
                "failed_outcomes": [],
                "failed_job_ids": [],
                "recovery": None,
                "expected_cutoff": expected,
                "last_prestart_success": prior,
            }
            active[key] = incident
            result.append(incident)
        active[key]["expected_cutoff"] = active[key]["expected_cutoff"] and expected
        active[key]["failures"] += 1
        active[key]["failed_attempt_ids"].append(row["id"])
        active[key]["failed_outcomes"].append(row["outcome"])
        active[key]["failed_job_ids"].append(row["job_id"])
        active[key]["last_failure_ms"] = row["attempted_at_ms"]
        active[key]["last_offset_minutes"] = row["offset_minutes"]
        active[key]["last_outcome"] = row["outcome"]
        active[key]["last_http_status"] = row["http_status"]
        active[key]["last_diagnostics_json"] = row["diagnostics_json"]
    removals = {
        row["job_id"]: dict(row)
        for row in connection.execute(
            text("SELECT * FROM schedule_removals")
        ).mappings()
    }
    for incident in result:
        incident["schedule_changed"] = all(
            job in removals for job in incident["failed_job_ids"]
        )
        day = (
            datetime.fromtimestamp(incident["starts_at_ms"] / 1000, WARSAW)
            .date()
            .isoformat()
        )
        request = (
            connection.execute(
                text(
                    "SELECT * FROM schedule_refresh_requests "
                    "WHERE cinema_id=:cinema AND target_date=:day"
                ),
                {"cinema": incident["cinema_id"], "day": day},
            )
            .mappings()
            .first()
        )
        incident["verification_pending"] = bool(
            incident["last_outcome"] == "screening_missing"
            and set(incident["failed_outcomes"]) == {"screening_missing"}
            and not incident["schedule_changed"]
            and not incident["recovery"]
            and request
            and request["state"] in {"pending", "running"}
            and request["requested_ms"] >= incident["first_failure_ms"]
            and now - incident["first_failure_ms"] < 15 * 60_000
        )
        if incident["last_outcome"] == "screening_missing" and request:
            incident["verification_outcome"] = (
                "Fresh repertoire still lists this booking"
                if request["outcome"] == "accepted" and not incident["schedule_changed"]
                else request["outcome"] or request["state"]
            )
    return result


def incident_message(incident: dict[str, Any]) -> str:
    from .pilot_health import local_time, safe_label

    recovery = incident["recovery"]
    availability = incident["last_outcome"] in {"sales_unavailable", "listing_absent"}
    headline = (
        "RECOVERED: seat checks"
        if recovery
        else ("SEAT AVAILABILITY UNAVAILABLE" if availability else "SEAT CHECK FAILED")
    )
    lines = [
        headline,
        cinema_name(incident.get("cinema_id", "kinoteka")),
        safe_label(incident["title"])[:180],
        "Screening: " + local_time(incident["starts_at_ms"]),
        "First failed attempt: " + local_time(incident["first_failure_ms"]),
        f"Unsuccessful attempts: {incident['failures']} | {incident['last_outcome']}",
        f"Latest scheduled check: T{incident.get('last_offset_minutes', 0):+d} minutes",
        "Latest attempt: " + local_time(incident["last_failure_ms"]),
    ]
    details = json.loads(incident.get("last_diagnostics_json") or "{}")
    if details.get("booking_url"):
        lines.append("Booking: " + str(details["booking_url"]))
    if incident.get("verification_outcome"):
        lines.append("Schedule verification: " + str(incident["verification_outcome"]))
    reasons = {
        "Seat counts disagree": (
            "Published seat counts do not agree with the selectable "
            "map or its capacity."
        ),
        "Missing capacity markers": (
            "The returned page did not contain the expected "
            "availability/capacity labels."
        ),
        "Session handshake unavailable": (
            "The returned page lacked the session fields needed to open the seat map."
        ),
        "Seat page unavailable; closure not established": (
            "The response was not the expected seat-map page."
        ),
        "Unapproved redirect": (
            "Booking redirected outside the approved cinema endpoint; stopped."
        ),
        "Redirect limit": "Booking exceeded the permitted redirect count; stopped.",
    }
    fallback = {
        "network_error": (
            "A network connection failed; no valid seat count was obtained."
        ),
        "timeout": "The cinema did not respond within the request time limit.",
        "blocked": "The cinema returned an access block or rate limit.",
        "tls_error": "The HTTPS connection could not be verified.",
        "deadline_exceeded": "The observation reached its cutoff before completion.",
        "invalid_data": (
            "The response could not be validated. This older "
            "attempt has no detailed response evidence."
        ),
    }
    reason = str(details.get("reason", ""))
    lines.append(
        "Cause: "
        + reasons.get(
            reason,
            reason
            or fallback.get(
                incident["last_outcome"],
                "The request failed; no valid seat count was obtained.",
            ),
        )
    )
    page = str(details.get("response_text", ""))
    if "Sprzedaż biletów dla wybranego wydarzenia jest niedostępna" in page:
        lines.append(
            "Page says: ticket sales for this event are unavailable. Sold-out "
            "versus sales cutoff is not established."
        )
    if availability:
        lines.append(
            "Availability observation, not proof of a collector outage "
            "or a sold-out screening."
        )
    if details:
        lines.append("Check step: " + safe_label(str(details.get("phase", "unknown"))))
        if details.get("path"):
            lines.append("Returned page: " + safe_label(str(details["path"])))
        if (
            details.get("available_controls") is not None
            and details.get("phase") == "seat_map"
            and not availability
        ):
            lines.append(
                f"Selectable controls in response: {details['available_controls']}"
            )
        if details.get("published_available") is not None:
            lines.append(
                f"Published availability: {details['published_available']} / "
                f"{details.get('published_capacity', 'unknown')} capacity"
            )
        if details.get("response_text") is not None:
            lines.append("Sanitized response text saved in SQLite for investigation.")
    if incident.get("last_http_status") is not None:
        lines.append(f"HTTP: {incident['last_http_status']}")
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
