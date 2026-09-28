import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from cinema_agg.server.app import create_app
from cinema_agg.server.contracts import utc_milliseconds
from cinema_agg.server.database import database_engine, migrate
from cinema_agg.server.importer import import_snapshot
from cinema_agg.server.settings import Settings


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'database with % & space.sqlite3'
    migrate(path)
    return path


@pytest.fixture
def payload():
    row = {
        'cinema_id': 'example', 'cinema_name': 'Cinema Żółć',
        'title_raw': 'Example', 'title_norm': 'example',
        'starts_at': '2026-09-28T20:00:00',
        'scraped_at': '2026-09-28T10:00:00',
        'duration_min': 0, 'language': 'org', 'tags': ['2D'],
        'booking_url': 'https://example.com/book?event=1', 'poster_url': None,
    }
    # Same title/time but distinct booking: must not collapse halls/events.
    other = dict(row, booking_url='https://example.com/book?event=2')
    third = dict(row, cinema_id='other', starts_at='2026-09-28T19:00:00')
    return {'generated_at': '2026-09-28T10:05:00', 'screenings': [row, other, third]}


def write_source(tmp_path, payload):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return source


def client_for(database):
    return TestClient(create_app(Settings(database_path=database)))


def test_import_query_pagination_filter_and_idempotency(database, tmp_path, payload):
    source = write_source(tmp_path, payload)
    imported = import_snapshot(database, source, 'Europe/Warsaw')
    again = import_snapshot(database, source, 'Europe/Warsaw')
    assert again['status'] == 'already_imported'
    assert again['snapshot_id'] == imported['snapshot_id']
    migrate(database)  # Upgrade is repeatable and preserves rows.
    with client_for(database) as client:
        page = client.get('/api/v1/screenings', params={'limit': 2}).json()
        assert page['total'] == 3
        assert page['next_offset'] == 2
        assert page['snapshot']['generated_at'] == '2026-09-28T08:05:00Z'
        assert page['screenings'][0]['starts_at'] == '2026-09-28T17:00:00Z'
        assert page['screenings'][0]['duration_min'] is None
        next_page = client.get('/api/v1/screenings', params={
            'limit': 2, 'offset': 2, 'snapshot_id': page['snapshot']['id'],
        }).json()
        assert next_page['next_offset'] is None
        assert len({r['id'] for r in page['screenings'] + next_page['screenings']}) == 3
        selected = client.get('/api/v1/screenings', params={'cinema_id': 'example'}).json()
        assert selected['total'] == 2
        assert selected['screenings'][0]['cinema_name'] == 'Cinema Żółć'
        assert client.get('/health/ready').status_code == 200
        assert client.get('/api/v1/screenings', params={
            'cinema_id': "' OR 1=1 --",
        }).json()['total'] == 0


@pytest.mark.parametrize('params', [
    {'limit': 201}, {'limit': 0}, {'offset': -1}, {'offset': 50001},
    {'snapshot_id': 'invalid'},
])
def test_invalid_pagination(database, params):
    with client_for(database) as client:
        assert client.get('/api/v1/screenings', params=params).status_code == 422


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / 'missing.sqlite3'
    with client_for(missing) as client:
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').status_code == 503
        response = client.get('/api/v1/screenings')
        assert response.status_code == 503
        assert str(missing) not in response.text
    assert not missing.exists()


def test_empty_and_incompatible_database(database):
    with client_for(database) as client:
        page = client.get('/api/v1/screenings').json()
        assert page['snapshot'] is None and page['screenings'] == []
        assert client.get('/api/v1/screenings', params={
            'snapshot_id': 'a' * 64,
        }).status_code == 404
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE alembic_version SET version_num='future'")
        assert client.get('/health/ready').status_code == 503
        assert client.get('/api/v1/screenings').status_code == 503
        assert client.get('/health/live').status_code == 200


def test_api_connection_cannot_write(database):
    engine = database_engine(database, readonly=True)
    try:
        with engine.begin() as connection, pytest.raises(SQLAlchemyError):
            connection.execute(text('DELETE FROM imports'))
    finally:
        engine.dispose()


def test_bad_empty_or_older_import_preserves_last_snapshot(database, tmp_path, payload):
    source = write_source(tmp_path, payload)
    imported = import_snapshot(database, source, 'Europe/Warsaw')
    variants = [
        dict(payload, screenings=[]),
        dict(payload, generated_at='2026-09-27T10:05:00'),
        dict(payload, screenings=[dict(payload['screenings'][0], booking_url='javascript:x')]),
    ]
    for bad in variants:
        source = write_source(tmp_path, bad)
        with pytest.raises(ValueError):
            import_snapshot(database, source, 'Europe/Warsaw')
    with client_for(database) as client:
        page = client.get('/api/v1/screenings').json()
        assert page['snapshot']['id'] == imported['snapshot_id']
        assert page['total'] == 3


def test_database_failure_rolls_back_entire_import(database, tmp_path, payload):
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TRIGGER reject_second BEFORE INSERT ON screenings
            WHEN NEW.ordinal = 1 BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(SQLAlchemyError):
        import_snapshot(database, write_source(tmp_path, payload), 'Europe/Warsaw')
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT count(*) FROM imports').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM screenings').fetchone()[0] == 0


def test_snapshot_pinning_survives_new_import(database, tmp_path, payload):
    old = import_snapshot(database, write_source(tmp_path, payload), 'Europe/Warsaw')
    changed = copy.deepcopy(payload)
    changed['generated_at'] = '2026-09-29T10:05:00'
    changed['screenings'][0]['title_raw'] = 'New title'
    new = import_snapshot(database, write_source(tmp_path, changed), 'Europe/Warsaw')
    with client_for(database) as client:
        assert client.get('/api/v1/screenings').json()['snapshot']['id'] == new['snapshot_id']
        historic = client.get('/api/v1/screenings', params={'snapshot_id': old['snapshot_id']}).json()
        assert all(row['title_raw'] == 'Example' for row in historic['screenings'])


def test_simultaneous_duplicate_import_is_serialized(database, tmp_path, payload):
    source = write_source(tmp_path, payload)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(import_snapshot, database, source, 'Europe/Warsaw')
                   for _ in range(2)]
        results = [future.result() for future in futures]
    assert {r['status'] for r in results} == {'imported', 'already_imported'}


@pytest.mark.parametrize('value', ['2026-03-29T02:30:00', '2026-10-25T02:30:00'])
def test_ambiguous_and_nonexistent_local_times_rejected(value):
    with pytest.raises(ValueError):
        utc_milliseconds(datetime.fromisoformat(value), 'Europe/Warsaw')


def test_offset_and_midnight_conversion():
    first = utc_milliseconds(datetime.fromisoformat('2026-10-25T02:30:00+02:00'), 'Europe/Warsaw')
    second = utc_milliseconds(datetime.fromisoformat('2026-10-25T02:30:00+01:00'), 'Europe/Warsaw')
    assert second - first == 3600000
    value = utc_milliseconds(datetime.fromisoformat('2026-09-28T00:30:00'), 'Europe/Warsaw')
    assert datetime.fromtimestamp(value / 1000, UTC).isoformat() == '2026-09-27T22:30:00+00:00'


def test_known_relative_links_only(database, tmp_path, payload):
    payload['screenings'][0].update(cinema_id='iluzjon', booking_url='filmy/info/123.html')
    import_snapshot(database, write_source(tmp_path, payload), 'Europe/Warsaw')
    with client_for(database) as client:
        page = client.get('/api/v1/screenings', params={'cinema_id': 'iluzjon'}).json()
        assert page['screenings'][0]['booking_url'] == 'https://www.iluzjon.fn.org.pl/filmy/info/123.html'
    payload['screenings'][0]['cinema_id'] = 'unknown'
    with pytest.raises(ValidationError):
        import_snapshot(database, write_source(tmp_path, payload), 'Europe/Warsaw')
