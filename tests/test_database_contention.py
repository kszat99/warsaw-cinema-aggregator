import sqlite3
import threading
import time
from sqlalchemy import event, text
from cinema_agg.server.database import database_engine, migrate
from cinema_agg.server.seat_pilot import latest_snapshot_id
from cinema_agg.server import database


def test_connection_setup_retries_exclusive_lock(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / "db.sqlite3"
    migrate(path)
    monkeypatch.setattr(database, 'BUSY_TIMEOUT_MS', 25)
    blocker = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    original_connect = sqlite3.connect
    waits = []

    class LockedJournalConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == 'PRAGMA journal_mode':
                super().execute('SELECT id FROM seat_worker_status')
            return super().execute(sql, *args, **kwargs)

    def connect_with_lock(*args, **kwargs):
        connection = original_connect(*args, factory=LockedJournalConnection, **kwargs)
        blocker.execute('BEGIN EXCLUSIVE')
        return connection

    def release_on_retry(message, attempt):
        waits.append((message, attempt))
        blocker.execute('ROLLBACK')

    monkeypatch.setattr(database.sqlite3, 'connect', connect_with_lock)
    monkeypatch.setattr(database, 'logging', SimpleNamespace(
        getLogger=lambda *args: SimpleNamespace(warning=release_on_retry)))
    engine = database_engine(path, readonly=False)
    try:
        with engine.begin() as connection:
            connection.execute(text('UPDATE seat_worker_status SET heartbeat_ms=456 WHERE id=1'))
        assert len(waits) == 1 and waits[0][1] == 1
        assert 'database_connection_lock_wait' in waits[0][0]
        assert blocker.execute('SELECT heartbeat_ms FROM seat_worker_status').fetchone()[0] == 456
    finally:
        blocker.close()
        engine.dispose()


def test_write_acquisition_retries_after_temporary_lock(tmp_path):
    path = tmp_path / "db.sqlite3"
    migrate(path)
    blocker = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    engine = database_engine(path, readonly=False)

    @event.listens_for(engine, "connect")
    def short_wait(connection, record):
        connection.execute("PRAGMA busy_timeout=25")

    def release():
        time.sleep(0.04)
        blocker.execute("ROLLBACK")

    thread = threading.Thread(target=release)
    thread.start()
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE seat_worker_status SET heartbeat_ms=123 WHERE id=1")
            )
        assert (
            blocker.execute("SELECT heartbeat_ms FROM seat_worker_status").fetchone()[0]
            == 123
        )
    finally:
        thread.join()
        blocker.close()
        engine.dispose()


def test_snapshot_poll_does_not_acquire_writer_lock(tmp_path):
    path = tmp_path / "db.sqlite3"
    migrate(path)
    blocker = sqlite3.connect(path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    engine = database_engine(path, readonly=False)
    try:
        assert latest_snapshot_id(engine) is None
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
        engine.dispose()
