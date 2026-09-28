"""Allowlisted JSON events: never serialize request data or exception messages."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TextIO

logger = logging.getLogger("cinema.api")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = (
            record.msg
            if record.msg
            in {
                "api_started",
                "api_stopped",
                "request_completed",
                "request_failed",
                "database_unavailable",
            }
            else "runtime_event"
        )
        fields: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "cinema-api",
            "event": event,
        }
        for key in ("request_id", "status_code", "duration_ms", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                fields[key] = value
        return json.dumps(fields, ensure_ascii=True)


def configure_logging(stream: TextIO | None = None) -> None:
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    # Scope changes to our service and Uvicorn; do not alter the legacy collector.
    for name in ("cinema.api", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers = [handler]
        target.setLevel(logging.INFO)
        target.propagate = False
