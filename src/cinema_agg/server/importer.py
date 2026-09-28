"""All-or-nothing local legacy import, independent of cinema collection."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .contracts import LegacySnapshot, utc_milliseconds
from .database import database_engine, require_schema

MAX_SOURCE_BYTES = 50 * 1024 * 1024


def import_snapshot(
    path: Path, source: Path, source_timezone: str
) -> dict[str, object]:
    ZoneInfo(
        source_timezone
    )  # Validate even when every timestamp already has an offset.
    with source.open("rb") as handle:
        raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds 50 MiB.")
    data = LegacySnapshot.model_validate_json(raw)
    source_hash = hashlib.sha256(raw).hexdigest()
    snapshot_id = hashlib.sha256(raw + b"\0" + source_timezone.encode()).hexdigest()
    generated = utc_milliseconds(data.generated_at, source_timezone)
    rows: list[dict[str, object]] = []
    for ordinal, screening in enumerate(data.screenings):
        row = screening.model_dump(exclude={"starts_at", "scraped_at", "tags"})
        row.update(
            snapshot_id=snapshot_id,
            ordinal=ordinal,
            starts_at_ms=utc_milliseconds(screening.starts_at, source_timezone),
            scraped_at_ms=utc_milliseconds(screening.scraped_at, source_timezone),
            tags=json.dumps(screening.tags, ensure_ascii=True),
        )
        rows.append(row)
    engine = database_engine(path, readonly=False)
    try:
        with engine.begin() as connection:
            require_schema(connection)
            exists = connection.execute(
                text("SELECT id FROM imports WHERE id = :id"),
                {"id": snapshot_id},
            ).scalar_one_or_none()
            if exists is not None:
                return {
                    "status": "already_imported",
                    "snapshot_id": snapshot_id,
                    "rows": len(rows),
                }
            latest = connection.execute(
                text("SELECT max(generated_at_ms) FROM imports")
            ).scalar()
            if latest is not None and generated <= latest:
                raise ValueError(
                    "Source must be newer than the latest imported snapshot."
                )
            connection.execute(
                text(
                    "INSERT INTO imports "
                    "(id, source_sha256, source_timezone, generated_at_ms, "
                    "imported_at_ms, row_count) "
                    "VALUES (:id, :sha, :zone, :generated, :imported, :rows)"
                ),
                {
                    "id": snapshot_id,
                    "sha": source_hash,
                    "zone": source_timezone,
                    "generated": generated,
                    "imported": utc_milliseconds(datetime.now(UTC), "UTC"),
                    "rows": len(rows),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO screenings "
                    "(snapshot_id, ordinal, cinema_id, cinema_name, title_raw, "
                    "title_norm, starts_at_ms, scraped_at_ms, duration_min, "
                    "language, tags, booking_url, poster_url) "
                    "VALUES (:snapshot_id, :ordinal, :cinema_id, :cinema_name, "
                    ":title_raw, :title_norm, "
                    ":starts_at_ms, :scraped_at_ms, :duration_min, :language, :tags, "
                    ":booking_url, :poster_url)"
                ),
                rows,
            )
    finally:
        engine.dispose()
    return {"status": "imported", "snapshot_id": snapshot_id, "rows": len(rows)}
