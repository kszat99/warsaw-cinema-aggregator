from sqlalchemy import text

from cinema_agg.server import alerts
from cinema_agg.server.pilot_health import report, job_lines
from cinema_agg.server.seat_pilot import claim, finish, plan, MINUTE
from cinema_agg.server.settings import Settings
from test_seat_pilot import NOW, engine  # noqa: F401
import pytest


@pytest.mark.parametrize('cinema,provider,url,outcome', [
    ('wisla','msi_wisla','https://wisla.novekino.pl/MSI/OrderTickets.aspx?event_id=123','sales_unavailable'),
    ('atlantic','msi_atlantic','https://atlantic.novekino.pl/MSI/OrderTickets.aspx?event_id=123','sales_unavailable'),
    ('amondo','amondo','https://kicket.com/embeddables/repertoire?organizerId=1772&showId=123','listing_absent'),
])
def test_expected_cutoff_retires_alert_without_fake_recovery(
    engine, tmp_path, monkeypatch, cinema, provider, url, outcome
):
    from cinema_agg.server.seat_pilot import PROVIDER_OFFSETS
    from cinema_agg.server.pilot_health import render
    monkeypatch.setitem(PROVIDER_OFFSETS, provider, (-5,0,5))
    with engine.begin() as db:
        db.execute(text('UPDATE screenings SET cinema_id=:cinema,booking_url=:url'),
                   {'cinema':cinema,'url':url})
    plan(engine,NOW)
    observation(engine,NOW,'success')
    observation(engine,NOW+5*MINUTE,outcome)
    path=tmp_path/'seats.sqlite3'
    data=report(path,NOW+6*MINUTE)
    incident=data['seat_incidents'][0]
    assert incident['expected_cutoff'] is True
    assert incident['recovery'] is None
    assert 'seat_incident_open' not in data['issues']
    assert 'EXPECTED CUTOFF (alert resolved)' in render(data)
    with engine.begin() as db:
        db.execute(text("INSERT INTO alert_state (fingerprint,state,first_seen_ms,last_seen_ms,last_notified_ms,evidence) VALUES (:fp,'open',:now,:now,:now,'{}')"),
                   {'fp':incident['fingerprint'],'now':NOW})
    original=alerts.report
    monkeypatch.setattr(alerts,'report',lambda *a,**k:{**original(*a,**k),'issues':[]})
    messages=[]
    monkeypatch.setattr(alerts,'send_telegram',lambda message,settings:(messages.append(message) or True,None))
    alerts.evaluate_alerts(path,NOW+6*MINUTE,Settings())
    assert messages == []
    with engine.connect() as db:
        state,evidence=db.execute(text('SELECT state,evidence FROM alert_state WHERE fingerprint=:fp'),{'fp':incident['fingerprint']}).one()
    assert state=='resolved' and 'expected_cutoff' in evidence


def test_prestart_unavailability_is_not_expected_cutoff(engine,tmp_path):
    plan(engine,NOW)
    observation(engine,NOW,'sales_unavailable')
    incident=report(tmp_path/'seats.sqlite3',NOW+MINUTE)['seat_incidents'][0]
    assert incident['expected_cutoff'] is False


def test_poststart_cutoff_without_prestart_counts_remains_open(engine,tmp_path,monkeypatch):
    from cinema_agg.server.seat_pilot import PROVIDER_OFFSETS
    monkeypatch.setitem(PROVIDER_OFFSETS,'msi_wisla',(-5,0,5))
    with engine.begin() as db:
        db.execute(text("UPDATE screenings SET cinema_id='wisla',booking_url='https://wisla.novekino.pl/MSI/OrderTickets.aspx?event_id=123'"))
    plan(engine,NOW)
    observation(engine,NOW,'invalid_data')
    observation(engine,NOW+5*MINUTE,'sales_unavailable')
    data=report(tmp_path/'seats.sqlite3',NOW+6*MINUTE)
    assert data['seat_incidents'][0]['expected_cutoff'] is False
    assert 'seat_incident_open' in data['issues']


def observation(engine, when, outcome):
    job = claim(engine, when)
    assert job
    ok = outcome == "success"
    finish(
        engine,
        job,
        dict(
            outcome=outcome,
            available=20 if ok else None,
            unavailable=5 if ok else None,
            capacity=25 if ok else None,
            http_status=200 if ok else None,
            cooldown_ms=0,
        ),
        when + 100,
    )
    return job


def test_same_screening_recovery_summary_and_recurrence(engine, tmp_path, monkeypatch):
    plan(engine, NOW)
    observation(engine, NOW, "network_error")
    observation(engine, NOW + 5 * MINUTE, "success")
    path = tmp_path / "seats.sqlite3"
    data = report(path, NOW + 6 * MINUTE)
    assert "seat_errors_in_window" in data["issues"]
    assert "seat_incident_open" not in data["issues"]
    assert data["seat_incidents"][0]["recovery"]["available"] == 20
    failed = data["evidence"]["failed_attempts"][0]
    detail = "\n".join(job_lines(failed, attempt=True))
    assert "RECOVERED:" in detail
    assert "separate scheduled T+0m check" in detail
    assert "20 available / 5 unavailable / 25 capacity" in detail
    assert "Original failed snapshot remains missing" in detail
    # Isolate incident notifications from fixture's missing refresh/backup warnings.
    original = alerts.report
    monkeypatch.setattr(
        alerts,
        "report",
        lambda *a, **k: {**original(*a, **k), "issues": ["seat_errors_in_window"]},
    )
    messages = []
    monkeypatch.setattr(
        alerts,
        "send_telegram",
        lambda message, settings: (messages.append(message) or True, None),
    )
    alerts.evaluate_alerts(path, NOW + 6 * MINUTE, Settings())
    assert len(messages) == 1 and messages[0].startswith("RECOVERED")
    alerts.evaluate_alerts(path, NOW + 7 * MINUTE, Settings())
    assert len(messages) == 1
    observation(engine, NOW + 10 * MINUTE, "timeout")
    alerts.evaluate_alerts(path, NOW + 11 * MINUTE, Settings())
    assert len(messages) == 2 and messages[-1].startswith("SEAT CHECK FAILED")
    # Passing time without success must never manufacture recovery.
    alerts.evaluate_alerts(path, NOW + 2 * 24 * 60 * MINUTE, Settings())
    assert len(messages) == 2


def test_other_screening_success_does_not_resolve(engine, tmp_path):
    plan(engine, NOW)
    observation(engine, NOW, "network_error")
    job = observation(engine, NOW + 5 * MINUTE, "success")
    with engine.begin() as db:
        db.execute(
            text("UPDATE seat_jobs SET cinema_event='different' WHERE id=:id"),
            {"id": job["id"]},
        )
    data = report(tmp_path / "seats.sqlite3", NOW + 6 * MINUTE)
    assert data["seat_incidents"][0]["recovery"] is None
    assert "seat_incident_open" in data["issues"]
    detail = "\n".join(job_lines(data["evidence"]["failed_attempts"][0], attempt=True))
    assert "UNRESOLVED:" in detail


def test_notified_failure_recovers_and_failed_recovery_delivery_retries(
    engine, tmp_path, monkeypatch
):
    plan(engine, NOW)
    observation(engine, NOW, "network_error")
    path = tmp_path / "seats.sqlite3"
    original = alerts.report
    monkeypatch.setattr(
        alerts, "report", lambda *a, **k: {**original(*a, **k), "issues": []}
    )
    results = iter([(True, None), (False, "timeout"), (True, None)])
    messages = []

    def send(message, settings):
        messages.append(message)
        return next(results)

    monkeypatch.setattr(alerts, "send_telegram", send)
    alerts.evaluate_alerts(path, NOW + MINUTE, Settings())
    assert messages[-1].startswith("SEAT CHECK FAILED")
    observation(engine, NOW + 5 * MINUTE, "success")
    alerts.evaluate_alerts(path, NOW + 6 * MINUTE, Settings())
    assert messages[-1].startswith("RECOVERED")
    with engine.connect() as db:
        assert (
            db.execute(text("SELECT state FROM alert_state")).scalar()
            == "pending_resolved"
        )
    alerts.evaluate_alerts(path, NOW + 7 * MINUTE, Settings())
    assert len(messages) == 2
    alerts.evaluate_alerts(path, NOW + 21 * MINUTE, Settings())
    assert len(messages) == 3
    with engine.connect() as db:
        assert db.execute(text("SELECT state FROM alert_state")).scalar() == "resolved"


def test_alert_includes_saved_failure_evidence(engine):
    import json
    from cinema_agg.server.seat_incidents import incidents, incident_message

    plan(engine, NOW)
    job = observation(engine, NOW, "invalid_data")
    with engine.begin() as db:
        db.execute(
            text(
                "UPDATE seat_observations SET http_status=200, diagnostics_json=:e WHERE job_id=:j"
            ),
            {
                "j": job["id"],
                "e": json.dumps(
                    {
                        "phase": "seat_map",
                        "reason": "Seat counts disagree",
                        "path": "/MSI/OrderTickets.aspx",
                        "available_controls": 482,
                        "response_text": "secret-long-body",
                    }
                ),
            },
        )
    with engine.connect() as db:
        message = incident_message(incidents(db, NOW + MINUTE)[0])
    assert "Published seat counts do not agree" in message
    assert "Check step: seat_map" in message
    assert "HTTP: 200" in message
    assert "482" in message
    assert "secret-long-body" not in message


def test_old_failure_alert_explains_missing_evidence(engine):
    from cinema_agg.server.seat_incidents import incidents, incident_message

    plan(engine, NOW)
    observation(engine, NOW, "invalid_data")
    with engine.connect() as db:
        message = incident_message(incidents(db, NOW + MINUTE)[0])
    assert "older attempt has no detailed response evidence" in message


def test_availability_notice_is_separate_from_technical_failure(engine, tmp_path):
    from cinema_agg.server.seat_incidents import incidents, incident_message

    plan(engine, NOW)
    observation(engine, NOW, "sales_unavailable")
    data = report(tmp_path / "seats.sqlite3", NOW + MINUTE)
    assert not data["evidence"]["failed_attempts"]
    assert len(data["evidence"]["availability_attempts"]) == 1
    with engine.connect() as db:
        message = incident_message(incidents(db, NOW + MINUTE)[0])
    assert message.startswith("SEAT AVAILABILITY UNAVAILABLE")
    assert "Latest scheduled check: T-5 minutes" in message
    assert "not proof of a collector outage" in message
