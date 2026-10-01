from sqlalchemy import text
from cinema_agg.server.seat_pilot import claim, finish, plan, MINUTE
from test_seat_pilot import engine, NOW  # noqa: F401
from test_multi_cinema_pilot import add_arkadia


def result(cooldown=0):
    return dict(
        outcome="blocked" if cooldown else "success",
        available=None if cooldown else 1,
        unavailable=None if cooldown else 1,
        capacity=None if cooldown else 2,
        http_status=429 if cooldown else 200,
        cooldown_ms=cooldown,
    )


def prepare(engine):
    add_arkadia(engine)
    plan(engine, NOW)
    with engine.begin() as c:
        c.execute(
            text("UPDATE seat_jobs SET due_at_ms=:now,deadline_ms=:deadline"),
            {"now": NOW, "deadline": NOW + 2 * MINUTE},
        )


def test_groups_can_be_claimed_concurrently_but_same_group_cannot(engine):
    prepare(engine)
    city = claim(engine, NOW, dispatch_group="cinema_city")
    kino = claim(engine, NOW, dispatch_group="kinoteka")
    assert city and kino
    assert city["provider"] == "cinema_city"
    assert kino["provider"] == "kinoteka"
    assert claim(engine, NOW, dispatch_group="cinema_city") is None
    assert claim(engine, NOW, dispatch_group="kinoteka") is None
    finish(engine, city, result(), NOW + 100)
    assert claim(engine, NOW + 5099, dispatch_group="cinema_city") is None
    assert claim(engine, NOW + 5100, dispatch_group="cinema_city") is not None


def test_blocked_group_does_not_block_other_provider(engine):
    prepare(engine)
    city = claim(engine, NOW, dispatch_group="cinema_city")
    finish(engine, city, result(15 * MINUTE), NOW + 100)
    assert claim(engine, NOW + 6000, dispatch_group="cinema_city") is None
    assert claim(engine, NOW + 6000, dispatch_group="kinoteka") is not None


def test_prestart_check_has_priority_over_poststart_same_deadline(engine):
    prepare(engine)
    with engine.begin() as c:
        c.execute(
            text("UPDATE seat_jobs SET state='superseded' WHERE provider='cinema_city'")
        )
    job = claim(engine, NOW, dispatch_group="kinoteka")
    assert job["offset_minutes"] == -5


def test_novekino_group_shares_lease_and_pacing_between_venues(engine):
    plan(engine, NOW)
    with engine.begin() as c:
        for venue in ["wisla", "atlantic"]:
            c.execute(
                text(
                    "INSERT INTO seat_provider_status(provider,cooldown_until_ms,activated_at_ms) VALUES (:p,0,:now) ON CONFLICT(provider) DO NOTHING"
                ),
                {"p": "msi_" + venue, "now": NOW},
            )
            c.execute(
                text(
                    "INSERT INTO seat_jobs(id,provider,cinema_id,provider_cinema,cinema_event,title,starts_at_ms,source_observed_ms,offset_minutes,purpose,due_at_ms,deadline_ms,state) VALUES (:id,:p,:v,:v,'123','Film',:start,:now,-5,'scheduled',:now,:deadline,'pending')"
                ),
                {
                    "id": venue,
                    "p": "msi_" + venue,
                    "v": venue,
                    "start": NOW + 5 * MINUTE,
                    "now": NOW,
                    "deadline": NOW + 2 * MINUTE,
                },
            )
    job = claim(engine, NOW, dispatch_group="novekino")
    assert job
    assert claim(engine, NOW, dispatch_group="novekino") is None
    finish(engine, job, result(), NOW + 100)
    assert claim(engine, NOW + 5099, dispatch_group="novekino") is None
    assert claim(engine, NOW + 5100, dispatch_group="novekino") is not None


def test_empty_group_does_not_crash_or_claim_other_provider(engine):
    plan(engine, NOW)
    assert claim(engine, NOW, dispatch_group="novekino") is None
    assert claim(engine, NOW, dispatch_group="cinema_city") is None
    assert claim(engine, NOW, dispatch_group="kinoteka") is not None
