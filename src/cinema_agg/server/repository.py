"""Read stored snapshots only; no upstream requests or schema mutation."""

import json

from sqlalchemy import Engine, text

from .contracts import ScreeningPage, ScreeningView, SnapshotView, utc_datetime
from .database import require_schema


class SnapshotNotFound(Exception):
    """Requested snapshot is absent."""


def screenings_page(
    engine: Engine,
    *,
    limit: int,
    offset: int,
    cinema_id: str | None = None,
    snapshot_id: str | None = None,
) -> ScreeningPage:
    with engine.connect() as connection, connection.begin():
        require_schema(connection)
        snapshot_query = "SELECT * FROM imports"
        if snapshot_id is not None:
            snapshot_query += " WHERE id = :snapshot_id"
        snapshot_query += " ORDER BY generated_at_ms DESC LIMIT 1"
        snapshot = (
            connection.execute(
                text(snapshot_query),
                {"snapshot_id": snapshot_id},
            )
            .mappings()
            .first()
        )
        run_query = "SELECT * FROM fetch_runs"
        if snapshot_id is not None:
            run_query += " WHERE snapshot_id=:snapshot_id"
        run_query += " ORDER BY started_at_ms DESC LIMIT 1"
        run = (
            connection.execute(
                text(run_query),
                {
                    "snapshot_id": snapshot_id,
                },
            )
            .mappings()
            .first()
        )
        collection = None
        if run is not None:
            results = connection.execute(
                text(
                    "SELECT cinema_id, target_date, outcome, count, previous_count, "
                    "duration_ms, error_type, observed_at_ms FROM fetch_results "
                    "WHERE run_id=:id ORDER BY cinema_id, target_date"
                ),
                {"id": run["id"]},
            ).mappings()
            collection = {
                "run_id": run["id"],
                "status": run["status"],
                "snapshot_id": run["snapshot_id"],
                "started_at": utc_datetime(run["started_at_ms"]).isoformat(),
                "finished_at": utc_datetime(run["finished_at_ms"]).isoformat()
                if run["finished_at_ms"] is not None
                else None,
                "results": [dict(result) for result in results],
            }
        if snapshot is None:
            if snapshot_id is not None:
                raise SnapshotNotFound
            return ScreeningPage(
                collection=collection,
                snapshot=None,
                total=0,
                limit=limit,
                offset=offset,
                next_offset=None,
                screenings=[],
            )
        params: dict[str, object] = {
            "snapshot_id": snapshot["id"],
            "limit": limit,
            "offset": offset,
        }
        condition = "snapshot_id = :snapshot_id"
        if cinema_id is not None:
            condition += " AND cinema_id = :cinema_id"
            params["cinema_id"] = cinema_id
        total = int(
            connection.execute(
                text("SELECT count(*) FROM screenings WHERE " + condition),
                params,
            ).scalar_one()
        )
        rows = connection.execute(
            text(
                "SELECT * FROM screenings WHERE "
                + condition
                + " ORDER BY starts_at_ms, ordinal LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings()
        screenings = [
            ScreeningView(
                id=f"{row['snapshot_id']}:{row['ordinal']}",
                cinema_id=row["cinema_id"],
                cinema_name=row["cinema_name"],
                title_raw=row["title_raw"],
                title_norm=row["title_norm"],
                starts_at=utc_datetime(row["starts_at_ms"]),
                scraped_at=utc_datetime(row["scraped_at_ms"]),
                duration_min=row["duration_min"],
                language=row["language"],
                tags=json.loads(row["tags"]),
                booking_url=row["booking_url"],
                poster_url=row["poster_url"],
            )
            for row in rows
        ]
        return ScreeningPage(
            collection=collection,
            snapshot=SnapshotView(
                id=snapshot["id"],
                generated_at=utc_datetime(snapshot["generated_at_ms"]),
                imported_at=utc_datetime(snapshot["imported_at_ms"]),
                source_timezone=snapshot["source_timezone"],
                row_count=snapshot["row_count"],
            ),
            total=total,
            limit=limit,
            offset=offset,
            next_offset=offset + limit if offset + limit < total else None,
            screenings=screenings,
        )
