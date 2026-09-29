"""Alert evaluation and delivery via Telegram."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from .database import database_engine, require_schema
from .pilot_health import ISSUE_HELP, report
from .settings import Settings


def format_alert_message(issue: str, data: dict[str, Any]) -> str:
    lines = [f"⚠️ *CINEMA PILOT: {issue}*"]
    lines.append(f"_{ISSUE_HELP.get(issue, 'Unknown issue')}_")
    
    if issue == "missed_jobs_in_window" or issue == "overdue_unfinished_jobs":
        evidence = data.get("evidence", {})
        problem_jobs = evidence.get("problem_jobs", [])
        if problem_jobs:
            lines.append("")
            lines.append(f"Affected jobs ({len(problem_jobs)}):")
            for job in problem_jobs[:3]:
                lines.append(f"• {job.get('title', 'Unknown')} T{job.get('offset_minutes', 0):+d}m")
            if len(problem_jobs) > 3:
                lines.append(f"  ...and {len(problem_jobs) - 3} more")
                
    elif issue == "seat_errors_in_window":
        evidence = data.get("evidence", {})
        failed = evidence.get("failed_attempts", [])
        if failed:
            lines.append("")
            lines.append(f"Failed attempts ({len(failed)}):")
            for f in failed[:3]:
                lines.append(f"• {f.get('title')} ({f.get('outcome')}) HTTP {f.get('http_status')}")
            if len(failed) > 3:
                lines.append(f"  ...and {len(failed) - 3} more")

    worker = data.get("worker", {})
    refresh = data.get("refresh", {})
    
    lines.append("")
    hb_age = worker.get("heartbeat_age_seconds")
    hb_icon = "✅" if hb_age is not None and hb_age <= 120 else "❌"
    lines.append(f"Worker heartbeat: {hb_icon} {f'{hb_age:.1f}s' if hb_age is not None else 'unknown'}")
    
    ref_age = refresh.get("last_success_age_minutes")
    ref_icon = "✅" if ref_age is not None and ref_age <= 420 else "❌"
    lines.append(f"Last refresh: {ref_icon} {f'{ref_age:.1f}m' if ref_age is not None else 'unknown'}")
    
    lines.append("")
    lines.append("🔧 `sudo cinema-pilot-status`")
    
    return "\n".join(lines)


def format_resolved_message(issue: str, data: dict[str, Any]) -> str:
    lines = [f"✅ *CINEMA PILOT: resolved*"]
    lines.append(f"`{issue}` cleared.")
    
    seats = data.get("seats", {})
    coverage = seats.get("coverage_percent")
    lines.append(f"Coverage: {seats.get('successful_jobs', 0)}/{seats.get('windows_finished', 0)} ({f'{coverage}%' if coverage is not None else 'unknown'}) last 24h")
    return "\n".join(lines)


def evaluate_alerts(path: Path, now: int, settings: Settings) -> None:
    data = report(path, now, hours=24)
    current_issues = set(data["issues"])
    
    engine = database_engine(path, readonly=False)
    
    telegram_token = settings.telegram_bot_token
    telegram_chat = settings.telegram_chat_id
    
    def send_telegram(text_md: str) -> bool:
        if not telegram_token or not telegram_chat:
            return False
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {"chat_id": telegram_chat, "text": text_md, "parse_mode": "Markdown"}
        try:
            resp = httpx.post(url, json=payload, timeout=10.0)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    with engine.begin() as conn:
        require_schema(conn)
        
        # Load existing open alerts
        existing = conn.execute(
            text("SELECT fingerprint, state, first_seen_ms FROM alert_state WHERE state = 'open'")
        ).mappings().all()
        
        open_alerts = {row["fingerprint"]: row for row in existing}
        
        # Check newly resolved alerts
        for fp, row in open_alerts.items():
            if fp not in current_issues:
                msg = format_resolved_message(fp, data)
                success = send_telegram(msg)
                
                conn.execute(
                    text(
                        "UPDATE alert_state SET state = 'resolved', "
                        "last_seen_ms = :now, "
                        "last_notified_ms = CASE WHEN :success THEN :now ELSE last_notified_ms END "
                        "WHERE fingerprint = :fp"
                    ),
                    {"now": now, "success": success, "fp": fp},
                )
        
        # Check new or continuing alerts
        for issue in current_issues:
            if issue not in open_alerts:
                # New alert!
                msg = format_alert_message(issue, data)
                success = send_telegram(msg)
                
                conn.execute(
                    text(
                        "INSERT INTO alert_state (fingerprint, state, first_seen_ms, "
                        "last_seen_ms, last_notified_ms, suppress_until_ms, impact, evidence) "
                        "VALUES (:fp, 'open', :now, :now, :notified, NULL, :impact, :evidence)"
                    ),
                    {
                        "fp": issue,
                        "now": now,
                        "notified": now if success else 0,
                        "impact": ISSUE_HELP.get(issue, ""),
                        "evidence": json.dumps(data.get("evidence", {})),
                    }
                )
            else:
                # Continuing alert. For now, we just update last_seen_ms. 
                # Bounded repeat logic could go here (e.g. notify again after 24h).
                conn.execute(
                    text(
                        "UPDATE alert_state SET last_seen_ms = :now "
                        "WHERE fingerprint = :fp"
                    ),
                    {"now": now, "fp": issue},
                )

    engine.dispose()


def main() -> None:
    settings = Settings.from_environment()
    now = int(datetime.now(UTC).timestamp() * 1000)
    try:
        evaluate_alerts(settings.database_path, now, settings)
    except Exception as e:
        # Failsafe: if we can't even open the DB or evaluate alerts, we can't write to alert_state.
        # So we try to send a fatal message to Telegram if configured.
        if settings.telegram_bot_token and settings.telegram_chat_id:
            try:
                httpx.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": settings.telegram_chat_id, 
                        "text": f"🚨 *CINEMA PILOT FATAL ERROR*\nAlert evaluation crashed:\n`{e.__class__.__name__}: {str(e)}`",
                        "parse_mode": "Markdown"
                    },
                    timeout=10.0
                )
            except Exception:
                pass
        raise SystemExit(1) from e

if __name__ == "__main__":
    main()
