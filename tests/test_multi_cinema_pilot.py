import httpx
from sqlalchemy import text

from cinema_agg.server import alerts
from cinema_agg.server.pilot_health import report, render
from cinema_agg.server.seat_pilot import MINUTE, claim, finish, plan, probe
from cinema_agg.server.settings import Settings
from test_seat_pilot import NOW, engine  # noqa: F401


def add_arkadia(engine, start=NOW + 5 * MINUTE):
    with engine.begin() as db:
        db.execute(text("""INSERT INTO screenings
            SELECT snapshot_id,ordinal+1,'1074','Cinema City Arkadia',title_raw,title_norm,
            :start,scraped_at_ms,duration_min,language,tags,
            'https://tickets.cinema-city.pl/api/order/12345?lang=pl',poster_url
            FROM screenings WHERE cinema_id='kinoteka'"""), {'start': start})


def done(engine, job, outcome, now, cooldown=0):
    ok = outcome == 'success'
    assert finish(engine, job, dict(outcome=outcome, available=1 if ok else None,
        unavailable=1 if ok else None, capacity=2 if ok else None,
        http_status=200 if ok else None, cooldown_ms=cooldown), now)


def test_two_venues_offsets_deduplicate_and_activation_skips_old_windows(engine):
    add_arkadia(engine, NOW)
    plan(engine, NOW)
    plan(engine, NOW + MINUTE)
    with engine.connect() as db:
        rows = db.execute(text('SELECT cinema_id,offset_minutes FROM seat_jobs')).all()
    assert sorted(off for cid, off in rows if cid == 'kinoteka') == [-5, 0, 5, 40]
    assert sorted(off for cid, off in rows if cid == '1074') == [0, 5, 10]


def test_city_block_does_not_block_kinoteka_and_survives_restart(engine):
    add_arkadia(engine)
    plan(engine, NOW)
    # Claim order is by stable job ID; finish either venue without assumptions.
    for stamp in (NOW, NOW+3000):
        job = claim(engine, stamp)
        done(engine, job, 'blocked' if job['cinema_id'] == '1074' else 'success',
             stamp+1, 15*MINUTE if job['cinema_id'] == '1074' else 0)
    job = claim(engine, NOW+5*MINUTE)
    assert job['cinema_id'] == 'kinoteka'
    done(engine, job, 'success', NOW+5*MINUTE+1)
    assert claim(engine, NOW+5*MINUTE+3000) is None
    with engine.connect() as db:
        assert db.execute(text("SELECT cooldown_until_ms FROM seat_provider_status "
            "WHERE provider='cinema_city'")).scalar_one() >= NOW+15*MINUTE


def test_city_dispatch_counts_and_http_block():
    from test_cinema_city_probe import client
    job = {'provider': 'cinema_city', 'cinema_id': '1074',
           'provider_cinema': '1074', 'cinema_event': '12345'}
    c, _ = client()
    with c:
        result = probe(c, job)
    assert (result['available'],result['unavailable'],result['capacity']) == (1,1,2)
    assert result['http_status'] == 200
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as c:
        result = probe(c, job)
    assert result['outcome'] == 'blocked' and result['cooldown_ms'] == 15*MINUTE
    assert result['available'] is None


def test_city_alerts_recovery_and_status_include_cinema(engine, tmp_path, monkeypatch):
    add_arkadia(engine)
    plan(engine, NOW, cinema_id='1074')
    job = claim(engine, NOW)
    done(engine, job, 'network_error', NOW+1)
    path = tmp_path/'seats.sqlite3'
    original = alerts.report
    monkeypatch.setattr(alerts, 'report', lambda *a, **k: {**original(*a, **k), 'issues': []})
    messages = []
    monkeypatch.setattr(alerts, 'send_telegram', lambda msg, cfg: (messages.append(msg) or True, None))
    alerts.evaluate_alerts(path, NOW+1000, Settings())
    assert 'Cinema City Arkadia' in messages[0] and 'FAILED' in messages[0]
    job = claim(engine, NOW+5*MINUTE)
    done(engine, job, 'success', NOW+5*MINUTE+1)
    alerts.evaluate_alerts(path, NOW+5*MINUTE+1000, Settings())
    assert len(messages) == 2 and 'RECOVERED' in messages[-1]
    data = report(path, NOW+8*MINUTE)
    city = next(c for c in data['cinemas'] if c['cinema_id'] == '1074')
    assert city['successful_jobs'] == 1 and city['windows_finished'] == 2
    assert 'Cinema City Arkadia' in render(data)
    alerts.evaluate_alerts(path, NOW+8*MINUTE, Settings())
    assert len(messages) == 2


def test_explicit_closure_is_not_an_error_or_a_recovery(engine, tmp_path):
    add_arkadia(engine)
    plan(engine, NOW, cinema_id='1074')
    done(engine, claim(engine, NOW), 'closed', NOW+1)
    data = report(tmp_path/'seats.sqlite3', NOW+3*MINUTE)
    assert 'seat_errors_in_window' not in data['issues']
    assert data['seats']['closed_jobs'] == 1
    assert data['seats']['successful_jobs'] == 0
    assert not data['seat_incidents']
    done(engine, claim(engine, NOW+5*MINUTE), 'network_error', NOW+5*MINUTE+1)
    done(engine, claim(engine, NOW+10*MINUTE), 'closed', NOW+10*MINUTE+1)
    assert report(tmp_path/'seats.sqlite3', NOW+11*MINUTE)['seat_incidents'][0]['recovery'] is None


def test_upgrade_preserves_old_job_ids_and_cooldown(tmp_path):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from cinema_agg.server import database
    path = tmp_path/'upgrade.sqlite3'
    db_engine = database.database_engine(path, readonly=False, create=True)
    config = Config()
    config.set_main_option('script_location', str(Path(database.__file__).parent/'migrations'))
    with db_engine.begin() as db:
        config.attributes['connection'] = db
        command.upgrade(config, '0004_alerts')
        db.execute(text("""INSERT INTO seat_jobs
          (id,cinema_event,provider_cinema,title,starts_at_ms,source_observed_ms,
           offset_minutes,purpose,due_at_ms,deadline_ms,state)
          VALUES ('old','event','venue','Film',1,1,40,'scheduled',1,2,'done')"""))
        db.execute(text("UPDATE seat_worker_status SET cooldown_until_ms=123456"))
    database.migrate(path)
    with db_engine.connect() as db:
        row = db.execute(text('SELECT id,provider,cinema_id,offset_minutes FROM seat_jobs')).one()
        assert tuple(row) == ('old','kinoteka','kinoteka',40)
        assert db.execute(text("SELECT cooldown_until_ms FROM seat_provider_status "
                               "WHERE provider='kinoteka'")).scalar_one() == 123456
        assert db.execute(text("SELECT activated_at_ms FROM seat_provider_status "
                               "WHERE provider='cinema_city'")).scalar_one() is None
    db_engine.dispose()
