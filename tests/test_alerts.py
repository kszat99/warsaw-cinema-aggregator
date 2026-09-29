import json

import httpx
from sqlalchemy import text

from cinema_agg.server import alerts
from cinema_agg.server.pilot_health import report, render
from cinema_agg.server.settings import Settings
from test_seat_pilot import NOW, engine  # noqa: F401


def test_failed_open_retries_then_deduplicates_and_recurs(engine, tmp_path, monkeypatch):
    data = {'issues': ['seat_errors_in_window'], 'evidence': {}}
    monkeypatch.setattr(alerts, 'report', lambda *a, **k: data)
    sent = []
    outcomes = iter([(False, 'timeout'), (True, None), (False, 'http_503'),
                     (True, None), (True, None)])
    def send(message, settings):
        # A second writer must be allowed during delivery (no long write lock).
        with engine.begin() as db:
            db.execute(text('UPDATE seat_worker_status SET heartbeat_ms=:now'), {'now': NOW})
        sent.append(message)
        return next(outcomes)
    monkeypatch.setattr(alerts, 'send_telegram', send)
    path = tmp_path / 'seats.sqlite3'
    def state():
        with engine.connect() as db:
            return dict(db.execute(text('SELECT * FROM alert_state')).mappings().one())
    alerts.evaluate_alerts(path, NOW, Settings())
    assert state()['state'] == 'pending_open'
    assert state()['last_notified_ms'] == 0
    output = render(report(path, NOW))
    assert 'notification_delivery_pending' in output and 'timeout' in output
    alerts.evaluate_alerts(path, NOW+1, Settings())
    assert len(sent) == 1
    alerts.evaluate_alerts(path, NOW+alerts.RETRY_MS, Settings())
    assert state()['state'] == 'open'
    alerts.evaluate_alerts(path, NOW+alerts.RETRY_MS+1, Settings())
    assert len(sent) == 2
    data['issues'] = []
    alerts.evaluate_alerts(path, NOW+2*alerts.RETRY_MS, Settings())
    assert state()['state'] == 'pending_resolved'
    alerts.evaluate_alerts(path, NOW+3*alerts.RETRY_MS, Settings())
    assert state()['state'] == 'resolved'
    data['issues'] = ['seat_errors_in_window']
    alerts.evaluate_alerts(path, NOW+4*alerts.RETRY_MS, Settings())
    assert state()['state'] == 'open'
    assert len(sent) == 5


def test_legacy_undelivered_alert_is_repaired(engine, tmp_path, monkeypatch):
    with engine.begin() as db:
        db.execute(text("INSERT INTO alert_state "
            "(fingerprint,state,first_seen_ms,last_seen_ms,last_notified_ms,evidence) "
            "VALUES ('seat_errors_in_window','open',:now,:now,0,'{}')"), {'now': NOW})
    monkeypatch.setattr(alerts, 'report', lambda *a, **k: {
        'issues': ['seat_errors_in_window', 'notification_delivery_pending'], 'evidence': {}})
    calls = []
    monkeypatch.setattr(alerts, 'send_telegram', lambda *a: (calls.append(a) or True, None))
    alerts.evaluate_alerts(tmp_path/'seats.sqlite3', NOW+1000, Settings())
    assert len(calls) == 1
    with engine.connect() as db:
        rows = db.execute(text('SELECT * FROM alert_state')).mappings().all()
    assert len(rows) == 1 and rows[0]['last_notified_ms'] == NOW+1000


def test_telegram_plain_text_and_failure_redaction(monkeypatch):
    settings = Settings(telegram_bot_token='test-token', telegram_chat_id='test-chat')
    def post(url, **kwargs):
        assert 'parse_mode' not in kwargs['json']
        return httpx.Response(200, json={'ok': False})
    monkeypatch.setattr(httpx, 'post', post)
    assert alerts.send_telegram('title_[*]', settings) == (False, 'telegram_rejected')
    def timeout(*a, **k):
        raise httpx.ReadTimeout('secret token must not appear')
    monkeypatch.setattr(httpx, 'post', timeout)
    assert alerts.send_telegram('text', settings) == (False, 'timeout')


def test_message_budget_and_no_markdown():
    message = alerts.format_alert_message('seat_errors_in_window', {
        'evidence': {'failed_attempts': [dict(title='x'*10000, outcome='network_error')]*5}})
    assert len(message) < 3500
    assert 'historical errors' in message
