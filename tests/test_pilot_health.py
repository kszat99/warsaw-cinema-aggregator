import os
import sqlite3

from sqlalchemy import text

from cinema_agg.server.database import migrate
from cinema_agg.server.pilot_health import MINUTE, backup_health, report
from cinema_agg.server.seat_pilot import claim, finish, plan
from test_seat_pilot import NOW, engine  # noqa: F401


def test_missing_db_does_not_create_file(tmp_path):
    import pytest
    path = tmp_path / 'absent.sqlite3'
    with pytest.raises(Exception):
        report(path, NOW)
    assert not path.exists()


def test_coverage_excludes_diagnostics_future_and_unfinished_windows(engine, tmp_path):
    plan(engine, NOW)
    job = claim(engine, NOW)
    finish(engine, job, dict(outcome='success', available=2, unavailable=3,
                            capacity=5, http_status=200, cooldown_ms=0), NOW+100)
    plan(engine, NOW, diagnostic=True)
    path = tmp_path / 'seats.sqlite3'
    early = report(path, NOW + MINUTE)
    assert early['seats']['windows_finished'] == 0
    assert early['seats']['coverage_percent'] is None
    result = report(path, NOW + 3*MINUTE)
    assert result['seats']['windows_finished'] == 1
    assert result['seats']['coverage_percent'] == 100
    assert result['seats']['attempt_outcomes'] == {'success': 1}
    assert 'worker_heartbeat_stale' in result['issues']
    assert 'schedule_refresh_stale' in result['issues']
    assert 'backup_missing' in result['issues']


def test_overdue_and_refresh_failure_visible(engine, tmp_path):
    plan(engine, NOW)
    with engine.begin() as db:
        db.execute(text("INSERT INTO fetch_runs(id,started_at_ms,finished_at_ms,status) "
                        "VALUES ('run',:now,:now,'partial')"), {'now': NOW})
    result = report(tmp_path / 'seats.sqlite3', NOW+3*MINUTE)
    assert result['seats']['overdue_unfinished'] == 1
    assert result['seats']['successful_jobs'] == 0
    assert 'latest_refresh_failed_or_partial' in result['issues']
    assert 'overdue_unfinished_jobs' in result['issues']


def test_backup_validation_and_age(tmp_path):
    assert backup_health(tmp_path, NOW)['status'] == 'missing'
    path = tmp_path / 'backup-20260929T000000.sqlite3'
    migrate(path)
    os.utime(path, (NOW/1000, NOW/1000))
    assert backup_health(tmp_path, NOW)['status'] == 'ok'
    assert backup_health(tmp_path, NOW+27*60*MINUTE)['status'] == 'stale'
    path.write_bytes(b'broken database')
    assert backup_health(tmp_path, NOW)['status'] == 'invalid'


def test_healthy_idle_worker_and_fresh_refresh(engine, tmp_path):
    with engine.begin() as db:
        db.execute(text('UPDATE seat_worker_status SET heartbeat_ms=:now'), {'now': NOW})
        db.execute(text("INSERT INTO fetch_runs(id,started_at_ms,finished_at_ms,status) "
                        "VALUES ('run',:now,:now,'complete')"), {'now': NOW})
    backups = tmp_path / 'backups'
    backups.mkdir()
    backup = backups / 'backup-20260929T000000.sqlite3'
    with sqlite3.connect(tmp_path / 'seats.sqlite3') as source, sqlite3.connect(backup) as dest:
        source.backup(dest)
    os.utime(backup, (NOW/1000, NOW/1000))
    result = report(tmp_path / 'seats.sqlite3', NOW)
    assert result['status'] == 'ok'
    assert result['seats']['coverage_percent'] is None
