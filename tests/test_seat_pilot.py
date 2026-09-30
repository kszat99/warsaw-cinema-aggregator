import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from cinema_agg.server.database import database_engine, migrate
from cinema_agg.server.importer import import_snapshot
from cinema_agg.server.seat_pilot import (
    MINUTE, booking_identity, claim, finish, plan, probe, status,
)

NOW = 1790700000000
CINEMA = '9ef78349-db9c-4dfc-85aa-96d030082c0d'
EVENT = '8b7a71ce-0961-4dd3-a621-4314dba4fe95'
URL = f'https://bilety.kinoteka.pl/#/screen?screeningId={EVENT}&cinemaId={CINEMA}'


@pytest.fixture
def engine(tmp_path):
    path = tmp_path / 'seats.sqlite3'
    migrate(path)
    stamp = lambda ms: datetime.fromtimestamp(ms / 1000, UTC).isoformat()
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({
        'generated_at': stamp(NOW - MINUTE),
        'screenings': [{
            'cinema_id': 'kinoteka', 'cinema_name': 'Kinoteka', 'title_raw': 'Example',
            'title_norm': 'example', 'starts_at': stamp(NOW + 5 * MINUTE),
            'scraped_at': stamp(NOW - MINUTE), 'booking_url': URL,
        }],
    }))
    import_snapshot(path, source, 'UTC')
    value = database_engine(path, readonly=False)
    yield value
    value.dispose()


def test_offsets_deduplicate_and_survive_restart(engine):
    plan(engine, NOW)
    plan(engine, NOW)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM seat_jobs')).scalar_one() == 4
        assert set(connection.execute(text('SELECT offset_minutes FROM seat_jobs')).scalars()) == {-5,0,5,40}
    first = claim(engine, NOW)
    assert first['offset_minutes'] == -5
    assert claim(engine, NOW + 1) is None
    assert finish(engine, first, {
        'outcome': 'success', 'available': 20, 'unavailable': 5, 'capacity': 25,
        'http_status': 200, 'cooldown_ms': 0,
    }, NOW + 100)
    assert claim(engine, NOW + MINUTE) is None
    assert status(engine)['outcomes'] == {'success': 1}


def test_expired_claim_is_recorded_and_fenced(engine):
    plan(engine, NOW)
    first = claim(engine, NOW)
    assert claim(engine, NOW + 3 * MINUTE) is None
    assert not finish(engine, first, {}, NOW + 3 * MINUTE)
    assert status(engine)['outcomes'] == {'interrupted': 1}
    assert status(engine)['jobs']['missed'] == 1


def test_diagnostic_is_separate_from_scheduled(engine):
    plan(engine, NOW)
    plan(engine, NOW, diagnostic=True)
    job = claim(engine, NOW, diagnostic_only=True)
    assert job['purpose'] == 'diagnostic'
    assert status(engine)['jobs']['pending'] == 4


@pytest.mark.parametrize('url', [
    'http://bilety.kinoteka.pl/?screeningId=x',
    'https://localhost/?screeningId=x', URL.replace(EVENT, '../../private'),
    URL + '&screeningId=' + EVENT,
])
def test_only_valid_provider_ids_and_origin(url):
    with pytest.raises(ValueError): booking_identity(url)


@pytest.mark.parametrize('payload', [
    {}, {'seatsLeft': None, 'totalOccupied': 2},
    {'seatsLeft': True, 'totalOccupied': 2},
    {'seatsLeft': 2, 'totalOccupied': -1},
    {'seatsLeft': 0, 'totalOccupied': 0},
])
def test_invalid_counts_are_not_zeroes(payload):
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    )) as client:
        result = probe(client, {'provider_cinema': CINEMA, 'cinema_event': EVENT})
    assert result['outcome'] == 'invalid_data'
    assert result['available'] is None and result['capacity'] is None


def test_endpoint_counts_and_404_semantics():
    def handle(request):
        assert request.method == 'GET'
        assert request.url.host == 'restapi.kinoteka.pl'
        assert request.url.path.endswith(f'/screening/{EVENT}/occupancy')
        return httpx.Response(200, json={'seatsLeft': 20, 'totalOccupied': 5})
    job = {'provider_cinema': CINEMA, 'cinema_event': EVENT}
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert probe(client, job)['capacity'] == 25
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
        result = probe(client, job)
        assert result['outcome'] == 'upstream_error'
        assert result['unavailable'] is None


def test_rate_limit_cooldown_is_persistent(engine):
    plan(engine, NOW)
    job = claim(engine, NOW)
    with httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(429, headers={'Retry-After': '1800'})
    )) as client:
        result = probe(client, job)
    finish(engine, job, result, NOW + 1)
    assert claim(engine, NOW + 5 * MINUTE) is None
    with engine.connect() as db:
        assert db.execute(text("SELECT cooldown_until_ms FROM seat_provider_status WHERE provider='kinoteka'")).scalar_one() >= NOW + 30 * MINUTE


def test_ambiguous_event_start_does_not_schedule(engine):
    with engine.begin() as connection:
        connection.execute(text('''INSERT INTO screenings
            SELECT snapshot_id, ordinal+1, cinema_id, cinema_name, title_raw, title_norm,
            starts_at_ms+3600000, scraped_at_ms, duration_min, language,tags,booking_url,poster_url
            FROM screenings'''))
    assert plan(engine, NOW) == 0
    assert status(engine)['jobs'] == {}
