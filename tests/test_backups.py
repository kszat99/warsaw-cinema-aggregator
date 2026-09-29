import os
import sqlite3
from datetime import datetime, timedelta

from cinema_agg.server.backups import backup, retention
from cinema_agg.server.database import migrate
from cinema_agg.server.pilot_health import backup_health


def test_retention_preserves_seven_days_four_older_weeks_and_manual_files(tmp_path):
    base = datetime(2026, 9, 29, 12)
    for offset in range(60):
        for hour in [0, 1]:
            stamp = base-timedelta(days=offset, hours=hour)
            (tmp_path/stamp.strftime('managed-backup-%Y%m%dT%H%M%S%f.sqlite3')).touch()
    manual = tmp_path/'backup-pre-migration.sqlite3'
    manual.touch()
    keep, remove = retention(tmp_path)
    assert len(keep) == 11
    assert len(remove) == 109
    assert manual not in remove
    assert len(set(p.name[15:23] for p in keep[:7])) == 7


def test_new_backup_restores_and_failed_source_never_prunes(tmp_path):
    import pytest
    source = tmp_path/'source.sqlite3'
    migrate(source)
    folder = tmp_path/'backups'
    result = backup(source, folder)
    with sqlite3.connect(folder/result['backup']) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT count(*) FROM seat_jobs').fetchone()[0] == 0
    previous = set(folder.iterdir())
    with pytest.raises(sqlite3.Error):
        backup(tmp_path/'missing.sqlite3', folder)
    assert set(folder.iterdir()) == previous


def test_latest_backup_is_selected_by_mtime_not_filename(tmp_path):
    older = tmp_path/'backup-zz-manual.sqlite3'
    newer = tmp_path/'backup-20260929T000000.sqlite3'
    migrate(older)
    migrate(newer)
    os.utime(older, (1000,1000))
    os.utime(newer, (2000,2000))
    assert backup_health(tmp_path, 2000000)['file'] == newer.name
