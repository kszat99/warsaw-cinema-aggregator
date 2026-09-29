from sqlalchemy import text

from cinema_agg.server import alerts
from cinema_agg.server.pilot_health import report, job_lines
from cinema_agg.server.seat_pilot import claim, finish, plan, MINUTE
from cinema_agg.server.settings import Settings
from test_seat_pilot import NOW, engine  # noqa: F401


def observation(engine, when, outcome):
    job = claim(engine, when)
    assert job
    ok = outcome == 'success'
    finish(engine, job, dict(outcome=outcome, available=20 if ok else None,
        unavailable=5 if ok else None, capacity=25 if ok else None,
        http_status=200 if ok else None, cooldown_ms=0), when+100)
    return job


def test_same_screening_recovery_summary_and_recurrence(engine, tmp_path, monkeypatch):
    plan(engine, NOW)
    observation(engine, NOW, 'network_error')
    observation(engine, NOW+5*MINUTE, 'success')
    path = tmp_path/'seats.sqlite3'
    data = report(path, NOW+6*MINUTE)
    assert 'seat_errors_in_window' in data['issues']
    assert 'seat_incident_open' not in data['issues']
    assert data['seat_incidents'][0]['recovery']['available'] == 20
    failed = data['evidence']['failed_attempts'][0]
    detail = '\n'.join(job_lines(failed, attempt=True))
    assert 'RECOVERED:' in detail
    assert 'separate scheduled T+0m check' in detail
    assert '20 available / 5 unavailable / 25 capacity' in detail
    assert 'Original failed snapshot remains missing' in detail
    # Isolate incident notifications from fixture's missing refresh/backup warnings.
    original = alerts.report
    monkeypatch.setattr(alerts, 'report', lambda *a, **k: {
        **original(*a, **k), 'issues': ['seat_errors_in_window']})
    messages = []
    monkeypatch.setattr(alerts, 'send_telegram', lambda message, settings:
        (messages.append(message) or True, None))
    alerts.evaluate_alerts(path, NOW+6*MINUTE, Settings())
    assert len(messages) == 1 and messages[0].startswith('RECOVERED')
    alerts.evaluate_alerts(path, NOW+7*MINUTE, Settings())
    assert len(messages) == 1
    observation(engine, NOW+10*MINUTE, 'timeout')
    alerts.evaluate_alerts(path, NOW+11*MINUTE, Settings())
    assert len(messages) == 2 and messages[-1].startswith('SEAT CHECK FAILED')
    # Passing time without success must never manufacture recovery.
    alerts.evaluate_alerts(path, NOW+2*24*60*MINUTE, Settings())
    assert len(messages) == 2


def test_other_screening_success_does_not_resolve(engine, tmp_path):
    plan(engine, NOW)
    observation(engine, NOW, 'network_error')
    job = observation(engine, NOW+5*MINUTE, 'success')
    with engine.begin() as db:
        db.execute(text("UPDATE seat_jobs SET cinema_event='different' WHERE id=:id"),
                   {'id': job['id']})
    data = report(tmp_path/'seats.sqlite3', NOW+6*MINUTE)
    assert data['seat_incidents'][0]['recovery'] is None
    assert 'seat_incident_open' in data['issues']
    detail = '\n'.join(job_lines(data['evidence']['failed_attempts'][0], attempt=True))
    assert 'UNRESOLVED:' in detail


def test_notified_failure_recovers_and_failed_recovery_delivery_retries(engine, tmp_path, monkeypatch):
    plan(engine, NOW)
    observation(engine, NOW, 'network_error')
    path = tmp_path/'seats.sqlite3'
    original = alerts.report
    monkeypatch.setattr(alerts, 'report', lambda *a, **k: {
        **original(*a, **k), 'issues': []})
    results = iter([(True, None), (False, 'timeout'), (True, None)])
    messages = []
    def send(message, settings):
        messages.append(message)
        return next(results)
    monkeypatch.setattr(alerts, 'send_telegram', send)
    alerts.evaluate_alerts(path, NOW+MINUTE, Settings())
    assert messages[-1].startswith('SEAT CHECK FAILED')
    observation(engine, NOW+5*MINUTE, 'success')
    alerts.evaluate_alerts(path, NOW+6*MINUTE, Settings())
    assert messages[-1].startswith('RECOVERED')
    with engine.connect() as db:
        assert db.execute(text('SELECT state FROM alert_state')).scalar() == 'pending_resolved'
    alerts.evaluate_alerts(path, NOW+7*MINUTE, Settings())
    assert len(messages) == 2
    alerts.evaluate_alerts(path, NOW+21*MINUTE, Settings())
    assert len(messages) == 3
    with engine.connect() as db:
        assert db.execute(text('SELECT state FROM alert_state')).scalar() == 'resolved'
