"""Explicit migrations and short SQLite transactions; API connections are read-only."""

import logging
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

SCHEMA_REVISION = "0010_schedule_changes"
BUSY_TIMEOUT_MS = 5000


class SchemaUnavailable(Exception):
    """The database must be initialized/upgraded by the operator."""


def database_engine(path: Path, *, readonly: bool, create: bool = False) -> Engine:
    resolved = path.expanduser().resolve()
    mode = "ro" if readonly else ("rwc" if create else "rw")

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(
            resolved.as_uri() + f"?mode={mode}",
            uri=True,
            check_same_thread=False,
            isolation_level=None,
            timeout=BUSY_TIMEOUT_MS / 1000,
        )
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            if readonly:
                connection.execute("PRAGMA query_only=ON")
            else:
                # A concurrent writer can hold an exclusive lock even before BEGIN.
                # Only retry this read-only setup check; never replay mutations.
                for attempt in range(3):
                    try:
                        journal_mode = connection.execute(
                            "PRAGMA journal_mode"
                        ).fetchone()[0]
                        break
                    except sqlite3.OperationalError as exc:
                        code = getattr(exc, "sqlite_errorcode", None)
                        if (
                            code is None
                            or code & 255 != sqlite3.SQLITE_BUSY
                            or attempt == 2
                        ):
                            raise
                        logging.getLogger(__name__).warning(
                            "database_connection_lock_wait retry=%s max_retries=2",
                            attempt + 1,
                        )
                if journal_mode != "delete":
                    raise SchemaUnavailable(
                        "This local slice requires DELETE journal mode."
                    )
        except BaseException:
            connection.close()
            raise
        return connection

    engine = create_engine("sqlite://", creator=connect, poolclass=NullPool)

    @event.listens_for(engine, "begin")
    def begin(connection: Connection) -> None:
        # Explicit transactions also cover SELECTs/DDL on Python's legacy sqlite driver.
        for attempt in range(3):
            try:
                connection.exec_driver_sql("BEGIN" if readonly else "BEGIN IMMEDIATE")
                return
            except OperationalError as exc:
                code = getattr(exc.orig, "sqlite_errorcode", None)
                if (
                    readonly
                    or code is None
                    or code & 255 != sqlite3.SQLITE_BUSY
                    or attempt == 2
                ):
                    raise
                # Retry acquisition only, before any transactional work occurs.
                logging.getLogger(__name__).warning(
                    "database_write_lock_wait retry=%s max_retries=2", attempt + 1
                )

    return engine


def require_schema(connection: Connection) -> None:
    versions = (
        connection.execute(text("SELECT version_num FROM alembic_version"))
        .scalars()
        .all()
    )
    if versions != [SCHEMA_REVISION]:
        raise SchemaUnavailable("Database schema does not match this application.")
    connection.execute(
        text("SELECT job_id,run_id,verified_ms FROM schedule_removals LIMIT 0")
    )
    connection.execute(
        text(
            "SELECT cinema_id,target_date,state FROM schedule_refresh_requests LIMIT 0"
        )
    )
    connection.execute(text("SELECT id, status, snapshot_id FROM fetch_runs LIMIT 0"))
    connection.execute(
        text(
            "SELECT run_id, outcome, previous_upcoming, fetched_upcoming "
            "FROM fetch_results LIMIT 0"
        )
    )
    connection.execute(
        text("SELECT provider,cinema_id,retry_at_ms FROM seat_jobs LIMIT 0")
    )
    connection.execute(
        text(
            "SELECT provider,activated_at_ms,cooldown_until_ms "
            "FROM seat_provider_status LIMIT 0"
        )
    )
    # Check expected columns too, rather than trusting only the version marker.
    connection.execute(
        text(
            "SELECT id, source_sha256, source_timezone, generated_at_ms, "
            "imported_at_ms, "
            "row_count FROM imports LIMIT 0"
        )
    )
    connection.execute(
        text(
            "SELECT snapshot_id, ordinal, cinema_id, cinema_name, title_raw, "
            "title_norm, "
            "starts_at_ms, scraped_at_ms, duration_min, language, tags, booking_url, "
            "poster_url FROM screenings LIMIT 0"
        )
    )


def migrate(path: Path) -> None:
    """Only this operator command creates directories, files or tables."""
    path.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = database_engine(path, readonly=False, create=True)
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).parent / "migrations").replace("%", "%%"),
    )
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            require_schema(connection)
    finally:
        engine.dispose()
