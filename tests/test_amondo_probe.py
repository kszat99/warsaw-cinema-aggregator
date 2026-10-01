import json
from datetime import datetime

import httpx
import pytest
from sqlalchemy import text

from cinema_agg.server.amondo_probe import booking_identity, probe
from cinema_agg.server.seat_pilot import MINUTE, claim, finish, plan
from test_seat_pilot import NOW, engine  # noqa: F401

START = int(datetime.fromisoformat('2026-10-01T17:30:00+02:00').timestamp()*1000)


def responses(*, missing=False, available=True, wrong_event=False, duplicate=False):
    events = [] if missing else [{'id':'123', 'show':{'id':'33127'},
        'organizer':{'id':1772}, 'displayPeriod':{'startsAt':'2026-10-01T17:30:00+02:00'}}]
    places = [{'id':'seat1', 'placeType':'NUMBERED', 'remainingQuantity':1}]
    if duplicate:
        places *= 2
    sales = [{'eventId':124 if wrong_event else 123, 'saleInfo':{'primarySale':{
        'availability':{'available':available, 'status':'AVAILABLE_NOW',
                        'stopDate':'2026-10-01T17:30:00'}, 'availablePlaces':places}}}]
    layout = {'classicSeatsPlanData':{'schema':json.dumps({'image':
        '<svg><path data-type="place" data-row="I" data-place="1"/>'
        '<path data-type="place" data-row="I" data-place="2"/></svg>'})}}
    return [events, sales, layout]


def run(payloads, start=START, status=200):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=payloads[len(calls)-1])
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = probe(client, '33127', start)
    return result, calls


def test_count_and_three_read_only_requests():
    result, calls = run(responses())
    assert result['outcome'] == 'success'
    assert (result['available'], result['unavailable'], result['capacity']) == (1,1,2)
    assert len(calls) == 3 and all(r.method == 'GET' for r in calls)
    assert result['diagnostics']['sales_stop_at'] == '2026-10-01T17:30:00'


def test_missing_or_different_showtime_never_uses_nearest_event():
    for payloads, start in [(responses(missing=True),START), (responses(),START+MINUTE)]:
        result, calls = run(payloads,start)
        assert result['outcome'] == 'listing_absent' and len(calls) == 1
        assert result['capacity'] is None


def test_explicit_sales_unavailable():
    result,calls = run(responses(available=False))
    assert result['outcome'] == 'sales_unavailable' and len(calls) == 2
    assert result['available'] is None


@pytest.mark.parametrize('kwargs', [{'wrong_event':True}, {'duplicate':True}])
def test_rejects_bad_identity_and_duplicate_seats(kwargs):
    result,_ = run(responses(**kwargs))
    assert result['outcome'] == 'data_validation_error'
    assert result['capacity'] is None


@pytest.mark.parametrize('status,outcome', [(500,'upstream_error'),(429,'blocked')])
def test_http_failures(status,outcome):
    result,calls = run(responses(),status=status)
    assert result['outcome'] == outcome and len(calls) == 1
    assert result['http_status'] == status


def test_booking_identity_allowlist():
    assert booking_identity('https://kicket.com/embeddables/repertoire?organizerId=1772&showId=33127') == ('1772','33127')
    with pytest.raises(ValueError):
        booking_identity('https://evil.example/embeddables/repertoire?organizerId=1772&showId=33127')


def test_background_plan_and_persistence(engine):
    with engine.begin() as db:
        db.execute(text("""INSERT INTO screenings
            SELECT snapshot_id,ordinal+1,'amondo','Kino Amondo',title_raw,title_norm,
            :start,scraped_at_ms,duration_min,language,tags,
            'https://kicket.com/embeddables/repertoire?organizerId=1772&showId=33127',poster_url
            FROM screenings WHERE cinema_id='kinoteka'"""), {'start':NOW+5*MINUTE})
    assert plan(engine,NOW,cinema_id='amondo') == 4
    plan(engine,NOW,cinema_id='amondo')
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM seat_jobs WHERE cinema_id='amondo'")).scalar_one() == 4
    job = claim(engine,NOW,dispatch_group='amondo')
    result,_ = run(responses())
    assert finish(engine,job,result,NOW+1000)
    with engine.connect() as db:
        assert db.execute(text("SELECT diagnostics_json FROM seat_observations WHERE job_id=:id"),{'id':job['id']}).scalar_one()


def test_same_show_on_two_dates_creates_independent_jobs(engine):
    with engine.begin() as db:
        for ordinal, start in [(10, NOW+60*MINUTE),(11,NOW+25*60*MINUTE)]:
            db.execute(text("""INSERT INTO screenings
                SELECT snapshot_id,:ordinal,'amondo','Kino Amondo',title_raw,title_norm,
                :start,scraped_at_ms,duration_min,language,tags,
                'https://kicket.com/embeddables/repertoire?organizerId=1772&showId=33127',poster_url
                FROM screenings WHERE cinema_id='kinoteka'"""), {'ordinal':ordinal,'start':start})
    plan(engine,NOW,cinema_id='amondo')
    plan(engine,NOW,cinema_id='amondo')
    with engine.connect() as db:
        rows=db.execute(text("SELECT starts_at_ms,state,count(*) FROM seat_jobs WHERE cinema_id='amondo' GROUP BY starts_at_ms,state")).all()
    assert len(rows)==2
    assert all(state=='pending' and count>0 for _,state,count in rows)
