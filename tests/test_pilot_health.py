import os
import sqlite3

from sqlalchemy import text

from cinema_agg.server.database import migrate
from cinema_agg.server.pilot_health import MINUTE, backup_health, report, render
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


def test_missed_checks_are_named_with_times_and_no_invented_cause(engine, tmp_path):
    plan(engine, NOW)
    claim(engine, NOW + 3*MINUTE)
    data = report(tmp_path / 'seats.sqlite3', NOW + 3*MINUTE)
    output = render(data)
    assert len(data['evidence']['problem_jobs']) == 1
    assert 'Example' in output
    assert 'NEVER ATTEMPTED' in output
    assert 'Planned:' in output and 'Deadline:' in output
    assert 'Why no attempt occurred was not recorded' in output
    assert 'missed_jobs_in_window' in output
    assert output.index('AFFECTED JOBS') < output.index('RECENT ATTEMPTS')


def test_failed_attempt_keeps_evidence_after_more_than_five_successes(engine, tmp_path):
    plan(engine, NOW)
    job = claim(engine, NOW)
    finish(engine, job, dict(outcome='blocked', available=None, unavailable=None,
                            capacity=None, http_status=429, cooldown_ms=0), NOW+100)
    # Later successes must not hide the older failure behind a recent-results limit.
    with engine.begin() as db:
        for i in range(6):
            db.execute(text("INSERT INTO seat_observations "
                "(id,job_id,attempted_at_ms,finished_at_ms,outcome,available,unavailable,capacity) "
                "VALUES (:id,:job,:stamp,:stamp,'success',2,3,5)"),
                {'id': str(i), 'job': job['id'], 'stamp': NOW+1000+i})
    data = report(tmp_path / 'seats.sqlite3', NOW+MINUTE)
    assert len(data['evidence']['recent_attempts']) == 5
    assert len(data['evidence']['failed_attempts']) == 1
    output = render(data)
    assert 'Result: blocked | HTTP: 429' in output
    assert 'Seats: unknown' in output
    assert 'seat_errors_in_window' in output


def test_success_timing_and_diagnostic_labels(engine, tmp_path):
    plan(engine, NOW)
    job = claim(engine, NOW+101000)
    finish(engine, job, dict(outcome='success', available=20, unavailable=5,
                            capacity=25, http_status=200, cooldown_ms=0), NOW+101100)
    plan(engine, NOW+102000, diagnostic=True)
    diag = claim(engine, NOW+104000, diagnostic_only=True)
    # The fixture screening is now less than five minutes away, so no diagnostic created.
    assert diag is None
    output = render(report(tmp_path / 'seats.sqlite3', NOW+105000))
    assert 'delay 101.0s (within 120s allowance)' in output
    assert '20 available / 5 unavailable / 25 capacity' in output
    assert 'Finished:' in output


def test_terminal_labels_cannot_inject_warning_lines():
    from cinema_agg.server.pilot_health import safe_label
    assert '\n' not in safe_label('title\nFAKE WARNING')
    assert '\x1b' not in safe_label('title\x1b[2J')


def test_diagnostic_does_not_imply_screening_start(engine, tmp_path):
    plan(engine, NOW, diagnostic=True)
    job = claim(engine, NOW, diagnostic_only=True)
    finish(engine, job, dict(outcome='success', available=2, unavailable=3,
                            capacity=5, http_status=200, cooldown_ms=0), NOW+100)
    output = render(report(tmp_path / 'seats.sqlite3', NOW+1000))
    assert 'MANUAL DIAGNOSTIC' in output
    assert '(manual check)' in output
    assert 'scheduled T+0' not in output
