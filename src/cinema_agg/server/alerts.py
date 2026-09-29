"""Durable Telegram delivery with retries; no network calls inside SQLite writes."""

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from .database import database_engine, require_schema
from .pilot_health import ISSUE_HELP, local_time, report, safe_label
from .settings import Settings

RETRY_MS = 15 * 60_000


def format_alert_message(issue: str, data: dict[str, Any]) -> str:
    # Plain text: provider titles/underscores must not break Telegram Markdown.
    lines = [f"CINEMA PILOT: {issue}", ISSUE_HELP.get(issue, "Unknown issue")]
    evidence = data.get("evidence", {})
    rows = (
        evidence.get("failed_attempts", [])
        if issue == "seat_errors_in_window"
        else evidence.get("problem_jobs", [])
    )
    if rows:
        lines.append(f"Records in report: {len(rows)} (showing up to 3)")
        for row in rows[:3]:
            title = safe_label(row.get("title", "Unknown"))[:180]
            lines.append(
                f"{title} | screening {local_time(row.get('starts_at_ms'))} "
                f"| T{row.get('offset_minutes', 0):+d}m"
            )
            if "outcome" in row:
                lines.append(
                    f"Attempt {local_time(row.get('attempted_at_ms'))}: "
                    f"{row['outcome']} HTTP {row.get('http_status')}"
                )
    lines.extend(
        [
            "This is a rolling 24-hour report; historical errors may remain "
            "after later successes.",
            "Details: sudo cinema-pilot-status",
        ]
    )
    return "\n".join(lines)[:3500]


def format_resolved_message(issue: str, data: dict[str, Any]) -> str:
    return (
        f"CINEMA PILOT: condition cleared\n{issue} is no longer present in "
        f"the health report.\n"
        "For historical issues this may mean the affected records left the "
        "24-hour window, "
        "not that a new successful request was observed.\nDetails: sudo "
        "cinema-pilot-status"
    )


def send_telegram(message: str, settings: Settings) -> tuple[bool, str | None]:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False, "not_configured"
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": message},
            timeout=8.0,
            follow_redirects=False,
        )
        if response.status_code != 200:
            return False, f"http_{response.status_code}"
        if response.json().get("ok") is not True:
            return False, "telegram_rejected"
        return True, None
    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.HTTPError:
        return False, "network_error"
    except (ValueError, AttributeError):
        return False, "invalid_response"


def evaluate_alerts(path: Path, now: int, settings: Settings) -> None:
    data = report(path, now, hours=24)
    # Delivery health cannot recursively generate its own delivery alert.
    current = set(data["issues"]) - {"notification_delivery_pending"}
    engine = database_engine(path, readonly=False)
    try:
        with engine.begin() as conn:
            require_schema(conn)
            previous = {
                r["fingerprint"]: dict(r)
                for r in conn.execute(text("SELECT * FROM alert_state")).mappings()
            }
            for issue in sorted(current | previous.keys()):
                old = previous.get(issue)
                active = issue in current
                state = old["state"] if old else "resolved"
                evidence = json.loads(old["evidence"] or "{}") if old else {}
                if active:
                    if state in {"resolved", "pending_resolved"}:
                        state = "pending_open"
                        evidence = {}
                    elif state == "open" and old and old["last_notified_ms"] == 0:
                        # Repair legacy records incorrectly marked open after fa
                        state = "pending_open"
                elif state in {"open", "pending_open"}:
                    state = "pending_resolved"
                    evidence = {}
                transition = old is None or state != old["state"]
                # Evidence refreshed each evaluation; preserve delivery attempt
                evidence.update({"report_issues": sorted(current)})
                conn.execute(
                    text(
                        "INSERT INTO alert_state (fingerprint,state,"
                        "first_seen_ms,last_seen_ms,"
                        "last_notified_ms,suppress_until_ms,impact,evidence) "
                        "VALUES (:fp,:state,:first,:now,:notified,:retry,"
                        ":impact,:evidence) "
                        "ON CONFLICT(fingerprint) DO UPDATE SET state=excluded.state, "
                        "first_seen_ms=excluded.first_seen_ms,"
                        "last_seen_ms=excluded.last_seen_ms, "
                        "suppress_until_ms=excluded.suppress_until_ms,"
                        "evidence=excluded.evidence"
                    ),
                    {
                        "fp": issue,
                        "state": state,
                        "now": now,
                        "first": now
                        if active and transition and state == "pending_open"
                        else (old["first_seen_ms"] if old else now),
                        "notified": old["last_notified_ms"] if old else 0,
                        "retry": (
                            None
                            if transition or old is None
                            else old["suppress_until_ms"]
                        ),
                        "impact": ISSUE_HELP.get(issue, ""),
                        "evidence": json.dumps(evidence),
                    },
                )
            pending = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT * FROM alert_state WHERE state IN "
                        "('pending_open','pending_resolved') "
                        "AND (suppress_until_ms IS NULL OR suppress_until_ms <= :now) "
                        "ORDER BY coalesce(suppress_until_ms,0),"
                        "first_seen_ms,fingerprint LIMIT 2"
                    ),
                    {"now": now},
                ).mappings()
            ]
        for item in pending:
            opening = item["state"] == "pending_open"
            message = (
                format_alert_message(item["fingerprint"], data)
                if opening
                else format_resolved_message(item["fingerprint"], data)
            )
            success, error = send_telegram(message, settings)
            evidence = json.loads(item["evidence"])
            evidence["delivery"] = {
                "attempted_at_ms": now,
                "error": error,
                "attempts": evidence.get("delivery", {}).get("attempts", 0) + 1,
            }
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE alert_state SET state=:state,"
                        "last_notified_ms=:notified,"
                        "suppress_until_ms=:retry,evidence=:evidence "
                        "WHERE fingerprint=:fp AND state=:expected AND "
                        "last_seen_ms=:now"
                    ),
                    {
                        "state": ("open" if opening else "resolved")
                        if success
                        else item["state"],
                        "notified": now if success else item["last_notified_ms"],
                        "retry": None if success else now + RETRY_MS,
                        "evidence": json.dumps(evidence),
                        "fp": item["fingerprint"],
                        "expected": item["state"],
                        "now": now,
                    },
                )
            print(
                json.dumps(
                    {
                        "event": "notification_delivery",
                        "issue": item["fingerprint"],
                        "transition": "open" if opening else "cleared",
                        "delivered": success,
                        "error": error,
                    }
                ),
                flush=True,
            )
    finally:
        engine.dispose()


def main() -> None:
    settings = Settings.from_environment()
    try:
        # OS releases this lock on crashes. All operational invocations use this CLI.
        fcntl = importlib.import_module("fcntl")
        with settings.database_path.with_suffix(".alerts.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(json.dumps({"event": "alert_evaluation_already_running"}))
                return
            evaluate_alerts(
                settings.database_path,
                int(datetime.now(UTC).timestamp() * 1000),
                settings,
            )
    except Exception as error:
        # Never put raw exceptions, URLs or credentials into logs or Telegram.
        print(
            json.dumps(
                {"event": "alert_evaluation_failed", "error_type": type(error).__name__}
            ),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
