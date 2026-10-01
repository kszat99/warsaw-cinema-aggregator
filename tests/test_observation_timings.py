from sqlalchemy import text

from test_seat_pilot import NOW, engine  # noqa: F401
from cinema_agg.server.seat_pilot import MINUTE, claim, finish, plan
from cinema_agg.server.seat_providers import OFFSETS


def test_history_is_spread_deterministically_and_never_backfilled(engine):
    start = NOW + 26*60*MINUTE
    with engine.begin() as db:
        db.execute(text("UPDATE screenings SET starts_at_ms=:start"), {"start": start})
    plan(engine, NOW)
    with engine.connect() as db:
        first = db.execute(text("SELECT id,offset_minutes,due_at_ms FROM seat_jobs")).all()
    assert len(first) == len(OFFSETS['kinoteka'])
    for _, offset, due in first:
        jitter = due - (start + offset*MINUTE)
        assert 0 <= jitter < MINUTE if offset <= -30 else jitter == 0
    plan(engine, NOW)
    with engine.connect() as db:
        assert db.execute(text("SELECT id,offset_minutes,due_at_ms FROM seat_jobs")).all() == first
    with engine.begin() as db:
        db.execute(text("DELETE FROM seat_jobs"))
    plan(engine, start - 4*MINUTE)
    with engine.connect() as db:
        assert set(db.execute(text("SELECT offset_minutes FROM seat_jobs")).scalars()) == {0,5,40}


def setup_wisla(engine):
    with engine.begin() as db:
        db.execute(text("UPDATE screenings SET cinema_id='wisla', "
                        "booking_url='https://wisla.novekino.pl/MSI/OrderTickets.aspx?event_id=123'"))
    plan(engine, NOW)
    with engine.begin() as db:
        db.execute(text("DELETE FROM seat_jobs WHERE offset_minutes != -2"))


def test_final_wisla_check_skips_if_too_late_to_start(engine):
    setup_wisla(engine)
    assert claim(engine, NOW + 4*MINUTE) is None
    with engine.connect() as db:
        assert db.execute(text("SELECT state FROM seat_jobs")).scalar_one() == 'cutoff_skipped'


def test_late_final_result_cannot_store_counts(engine):
    setup_wisla(engine)
    job = claim(engine, NOW + 3*MINUTE)
    assert job is not None
    assert finish(engine, job, dict(outcome='success', available=1, unavailable=1,
                  capacity=2, http_status=200, cooldown_ms=0), NOW+5*MINUTE)
    with engine.connect() as db:
        row = db.execute(text("SELECT outcome,available FROM seat_observations")).one()
        assert row == ('deadline_exceeded', None)
