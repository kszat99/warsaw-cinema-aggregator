"""External evaluator heartbeat and bounded, private local delivery history."""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx


def validate_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.netloc != "hc-ping.com"
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Invalid heartbeat configuration")
    return "https://hc-ping.com/" + str(UUID(parts.path.removeprefix("/")))


def history_path(database: Path) -> Path:
    return database.with_name("heartbeat-history.sqlite3")


def send_heartbeat(database: Path) -> bool:
    value = os.environ.get("CINEMA_HEARTBEAT_URL")
    if not value:
        print(json.dumps({"event": "heartbeat", "outcome": "not_configured"}))
        return True  # Optional until the operator configures external monitoring.
    now = int(datetime.now(UTC).timestamp() * 1000)
    path = history_path(database)
    with sqlite3.connect(path, timeout=5) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS attempts ("
            "id INTEGER PRIMARY KEY, attempted_ms INTEGER NOT NULL,"
            "finished_ms INTEGER, outcome TEXT NOT NULL, http_status INTEGER)"
        )
        cursor = db.execute(
            "INSERT INTO attempts(attempted_ms,outcome) VALUES (?,?)", (now, "started")
        )
        attempt = cursor.lastrowid
        db.execute(
            "DELETE FROM attempts WHERE attempted_ms < ?", (now - 30 * 86400000,)
        )
        db.commit()  # Persist the attempt before network I/O; no write lock held.
        status = None
        outcome = "invalid_config"
        try:
            url = validate_url(value)
            response = httpx.get(url, timeout=5, follow_redirects=False)
            status = response.status_code
            outcome = (
                "acknowledged"
                if status == 200 and response.text.strip() == "OK"
                else "rejected"
            )
        except httpx.TimeoutException:
            outcome = "timeout"
        except httpx.HTTPError:
            outcome = "network_error"
        except ValueError:
            pass
        db.execute(
            "UPDATE attempts SET finished_ms=?,outcome=?,http_status=? WHERE id=?",
            (int(datetime.now(UTC).timestamp() * 1000), outcome, status, attempt),
        )
    print(
        json.dumps({"event": "heartbeat", "outcome": outcome, "http_status": status}),
        flush=True,
    )
    return outcome == "acknowledged"


def latest_heartbeat(database: Path) -> dict[str, Any] | None:
    path = history_path(database)
    if not path.exists():
        return None
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM attempts ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
