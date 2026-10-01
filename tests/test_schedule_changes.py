import asyncio
from datetime import datetime

from sqlalchemy import text

from cinema_agg.server import collector
from cinema_agg.server.contracts import LegacyScreening
from cinema_agg.server.pilot_health import report
from cinema_agg.server.schedule_changes import WARSAW, request_verification
from cinema_agg.server.seat_pilot import claim, finish, plan
from test_multi_cinema_pilot import add_arkadia
from test_seat_pilot import MINUTE, NOW, engine  # noqa: F401


def fresh(event='99999'):
    return LegacyScreening(
        scraped_at=datetime.fromtimestamp(NOW/1000,WARSAW),
        cinema_id='1074',cinema_name='Arkadia',title_raw='New',title_norm='new',
        starts_at=datetime.fromtimestamp((NOW+5*MINUTE)/1000,WARSAW),
        booking_url=f'https://tickets.cinema-city.pl/order/{event}?lang=pl',
    )


def refresh(tmp_path,monkeypatch,rows):
    monkeypatch.setattr(collector,'now_ms',lambda:NOW+2000)
    async def fetch(cinema,day):
        return rows
    return asyncio.run(collector.collect(
        tmp_path/'seats.sqlite3',['1074'],
        [datetime.fromtimestamp(NOW/1000,WARSAW).date()],fetch,delay_seconds=0))


def test_accepted_replacement_retires_old_jobs_and_retains_attempts(engine,tmp_path,monkeypatch):
    add_arkadia(engine)
    plan(engine,NOW)
    job=claim(engine,NOW,dispatch_group='cinema_city')
    assert finish(engine,job,dict(outcome='screening_missing',http_status=200,
        available=None,unavailable=None,capacity=None,cooldown_ms=0),NOW+1000)
    data=report(tmp_path/'seats.sqlite3',NOW+1500)
    assert data['seat_incidents'][0]['verification_pending']
    assert 'seat_incident_open' not in data['issues']
    result=refresh(tmp_path,monkeypatch,[fresh()])
    assert result['status']=='complete'
    plan(engine,NOW+2000)
    data=report(tmp_path/'seats.sqlite3',NOW+3000)
    assert data['seat_incidents'][0]['schedule_changed']
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM seat_jobs WHERE cinema_event='12345' AND state='pending'")).scalar_one()==0
        assert db.execute(text("SELECT count(*) FROM seat_observations WHERE job_id=:id"),{'id':job['id']}).scalar_one()==1
        assert db.execute(text("SELECT count(*) FROM seat_jobs WHERE cinema_event='99999' AND state='pending'")).scalar_one()>0
        assert db.execute(text("SELECT count(*) FROM seat_jobs WHERE cinema_id='kinoteka' AND state='pending'")).scalar_one()>0


def test_empty_refresh_never_cancels_jobs(engine,tmp_path,monkeypatch):
    add_arkadia(engine)
    plan(engine,NOW)
    assert refresh(tmp_path,monkeypatch,[])['status']=='failed'
    with engine.connect() as db:
        assert db.execute(text('SELECT count(*) FROM schedule_removals')).scalar_one()==0
        assert db.execute(text("SELECT count(*) FROM seat_jobs WHERE cinema_id='1074' AND state='pending'")).scalar_one()>0


def test_still_listed_missing_booking_becomes_actionable(engine,tmp_path,monkeypatch):
    add_arkadia(engine)
    plan(engine,NOW)
    job=claim(engine,NOW,dispatch_group='cinema_city')
    finish(engine,job,dict(outcome='screening_missing',http_status=200,
        available=None,unavailable=None,capacity=None,cooldown_ms=0),NOW+1000)
    refresh(tmp_path,monkeypatch,[fresh('12345')])
    data=report(tmp_path/'seats.sqlite3',NOW+3000)
    assert not data['seat_incidents'][0]['verification_pending']
    assert not data['seat_incidents'][0]['schedule_changed']
    assert 'seat_incident_open' in data['issues']


def test_requests_deduplicate_and_verification_grace_expires(engine,tmp_path):
    add_arkadia(engine)
    plan(engine,NOW)
    job=claim(engine,NOW,dispatch_group='cinema_city')
    finish(engine,job,dict(outcome='screening_missing',http_status=200,
        available=None,unavailable=None,capacity=None,cooldown_ms=0),NOW+1000)
    with engine.begin() as db:
        request_verification(db,job,NOW+2000)
        assert db.execute(text('SELECT count(*) FROM schedule_refresh_requests')).scalar_one()==1
    data=report(tmp_path/'seats.sqlite3',NOW+16*MINUTE)
    assert 'seat_incident_open' in data['issues']


def test_targeted_verification_fetches_single_scope_and_respects_spacing(engine,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from cinema_agg.server import schedule_changes
    add_arkadia(engine)
    plan(engine,NOW)
    job=claim(engine,NOW,dispatch_group='cinema_city')
    with engine.begin() as db:
        request_verification(db,job,NOW)
    finish(engine,job,dict(outcome='screening_missing',http_status=200,
        available=None,unavailable=None,capacity=None,cooldown_ms=0),NOW+1)
    calls=[]
    async def fetch(cinema,day):
        calls.append((cinema,day))
        return [fresh()]
    monkeypatch.setattr(collector,'make_fetch',lambda client:fetch)
    monkeypatch.setattr(collector,'now_ms',lambda:NOW+2000)
    monkeypatch.setattr(schedule_changes,'importlib',SimpleNamespace(
        import_module=lambda name:SimpleNamespace(flock=lambda *args:None,LOCK_EX=1,LOCK_NB=2)))
    assert schedule_changes.verify_next(tmp_path/'seats.sqlite3',NOW+6000)
    assert calls==[('1074',datetime.fromtimestamp(NOW/1000,WARSAW).date())]
    with engine.begin() as db:
        db.execute(text("INSERT INTO schedule_refresh_requests (cinema_id,target_date,requested_ms,due_ms,state) VALUES ('1070','2026-09-30',:now,:now,'pending')"),{'now':NOW})
    assert not schedule_changes.verify_next(tmp_path/'seats.sqlite3',NOW+7000)
    assert len(calls)==1


def test_verification_reserves_city_requests_but_not_other_provider(engine):
    add_arkadia(engine)
    plan(engine,NOW)
    with engine.begin() as db:
        db.execute(text("INSERT INTO schedule_refresh_requests (cinema_id,target_date,requested_ms,due_ms,started_ms,state) VALUES ('1074','2026-09-29',:now,:now,:now,'running')"),{'now':NOW})
    assert claim(engine,NOW,dispatch_group='cinema_city') is None
    assert claim(engine,NOW,dispatch_group='kinoteka') is not None
