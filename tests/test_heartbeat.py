import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from cinema_agg.server import alerts, heartbeat
from cinema_agg.server.settings import Settings

URL = 'https://hc-ping.com/00000000-0000-0000-0000-000000000001'


@pytest.mark.parametrize('body,status,expected', [
    ('OK', 200, 'acknowledged'), ('OK (not found)', 200, 'rejected'),
    ('OK (rate limited)', 200, 'rejected'), ('', 503, 'rejected')])
def test_acknowledgement_and_private_history(tmp_path, monkeypatch, body, status, expected):
    monkeypatch.setenv('CINEMA_HEARTBEAT_URL', URL)
    def get(url, **kwargs):
        assert kwargs['follow_redirects'] is False
        assert url == URL
        return httpx.Response(status, text=body)
    monkeypatch.setattr(httpx, 'get', get)
    path = tmp_path/'main.sqlite3'
    assert heartbeat.send_heartbeat(path) == (expected == 'acknowledged')
    assert heartbeat.latest_heartbeat(path)['outcome'] == expected
    assert URL.encode() not in heartbeat.history_path(path).read_bytes()
    assert not path.exists()


def test_timeout_redaction_and_retention(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('CINEMA_HEARTBEAT_URL', URL)
    def get(*a, **k):
        raise httpx.ReadTimeout(URL)
    monkeypatch.setattr(httpx, 'get', get)
    path = tmp_path/'main.sqlite3'
    assert not heartbeat.send_heartbeat(path)
    assert URL not in capsys.readouterr().out
    with sqlite3.connect(heartbeat.history_path(path)) as db:
        db.execute("INSERT INTO attempts(attempted_ms,outcome) VALUES(0,'old')")
    heartbeat.send_heartbeat(path)
    with sqlite3.connect(heartbeat.history_path(path)) as db:
        assert db.execute("SELECT count(*) FROM attempts WHERE outcome='old'").fetchone()[0] == 0


@pytest.mark.parametrize('url', ['http://hc-ping.com/x', 'https://example.com/x', URL+'/fail', URL+'?x=1'])
def test_rejects_unapproved_urls(url):
    with pytest.raises(ValueError):
        heartbeat.validate_url(url)


def test_heartbeat_only_after_completed_evaluation(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path/'main.sqlite3')
    monkeypatch.setattr(Settings, 'from_environment', lambda: settings)
    monkeypatch.setattr(alerts.importlib, 'import_module', lambda name:
        SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *a: None))
    events = []
    monkeypatch.setattr(alerts, 'evaluate_alerts', lambda *a: events.append('evaluated'))
    monkeypatch.setattr(alerts, 'send_heartbeat', lambda *a: events.append('ping') or True)
    alerts.main()
    assert events == ['evaluated', 'ping']
    def fail(*a):
        raise RuntimeError('test')
    monkeypatch.setattr(alerts, 'evaluate_alerts', fail)
    events.clear()
    with pytest.raises(SystemExit):
        alerts.main()
    assert events == []
