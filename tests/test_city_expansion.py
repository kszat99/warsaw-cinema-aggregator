import httpx
import pytest
from sqlalchemy import text

from test_seat_pilot import NOW, engine  # noqa: F401
from cinema_agg.server.seat_pilot import MINUTE, claim, finish, job_identity, plan, probe
from cinema_agg.server.seat_providers import CITY_CINEMAS


@pytest.mark.parametrize('cinema', list(CITY_CINEMAS))
def test_every_enabled_city_venue_plans_and_dispatches(engine, cinema):
    with engine.begin() as db:
        db.execute(text("UPDATE screenings SET cinema_id=:cinema, "
                        "booking_url='https://tickets.cinema-city.pl/order/123'"),
                   {'cinema': cinema})
    assert job_identity(cinema, 'https://tickets.cinema-city.pl/order/123') == (cinema, '123')
    plan(engine, NOW)
    plan(engine, NOW)
    with engine.connect() as db:
        assert db.execute(text('SELECT count(*) FROM seat_jobs')).scalar_one() == 4
    job = claim(engine, NOW)
    assert job['provider_cinema'] == cinema
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'error': {'error': 'TICKETING_ENDED'}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe(client, job)
    assert result['outcome'] == 'closed'
    assert len(calls) == 1


def test_city_dispatch_rejects_mismatched_venue_before_network():
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: pytest.fail('Unexpected network call')
    )) as client:
        result = probe(client, {'provider': 'cinema_city', 'cinema_id': '1061',
                               'provider_cinema': '1074', 'cinema_event': '123'})
    assert result['outcome'] == 'invalid_data'


def test_city_venues_share_one_cooldown(engine):
    with engine.begin() as db:
        db.execute(text("UPDATE screenings SET cinema_id='1061', "
                        "booking_url='https://tickets.cinema-city.pl/order/123'"))
    plan(engine, NOW)
    first = claim(engine, NOW)
    assert finish(engine, first, dict(outcome='blocked', available=None, unavailable=None,
                  capacity=None, http_status=429, cooldown_ms=15*60000), NOW+100)
    with engine.begin() as db:
        db.execute(text("UPDATE screenings SET cinema_id='1069', "
                        "booking_url='https://tickets.cinema-city.pl/order/456'"))
    plan(engine, NOW+100)
    # Janki's first passed slot is deliberately not backfilled; make next due for test.
    with engine.begin() as db:
        db.execute(text("UPDATE seat_jobs SET due_at_ms=:now WHERE cinema_id='1069'"),
                   {'now': NOW+6000})
    assert claim(engine, NOW+6000) is None


def test_early_snapshots_have_slack_and_close_checks_take_priority(engine):
    with engine.begin() as db:
        db.execute(text("UPDATE screenings SET starts_at_ms=:start"),
                   {'start': NOW + 26*60*MINUTE})
    plan(engine, NOW)
    with engine.connect() as db:
        rows = db.execute(text("SELECT offset_minutes,deadline_ms-due_at_ms FROM seat_jobs")).all()
    for offset, allowance in rows:
        assert allowance == (10 if offset <= -15 else 2)*MINUTE
    with engine.begin() as db:
        db.execute(text("UPDATE seat_jobs SET due_at_ms=:now, deadline_ms=:deadline, "
                        "state=CASE WHEN offset_minutes IN (-15,-5) THEN 'pending' "
                        "ELSE 'superseded' END"), {'now': NOW, 'deadline': NOW+10*MINUTE})
        db.execute(text("UPDATE seat_jobs SET deadline_ms=:deadline WHERE offset_minutes=-5"),
                   {'deadline': NOW+2*MINUTE})
    assert claim(engine, NOW)['offset_minutes'] == -5
