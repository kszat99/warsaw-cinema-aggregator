import pytest
from sqlalchemy import text

from cinema_agg.server import alerts
from cinema_agg.server.database import database_engine
from cinema_agg.server.pilot_health import report, render
from cinema_agg.server.seat_pilot import MINUTE, claim, finish, plan
from cinema_agg.server.settings import Settings
from test_multi_cinema_pilot import add_arkadia
from test_seat_pilot import NOW, engine  # noqa: F401


def result(outcome):
    ok = outcome == 'success'
    return dict(outcome=outcome, available=2 if ok else None,
                unavailable=3 if ok else None, capacity=5 if ok else None,
                http_status=200 if ok else None, cooldown_ms=0)


@pytest.mark.parametrize('cinema', ['kinoteka', '1074'])
def test_retry_survives_restart_and_recovers_same_window(engine, tmp_path, cinema, monkeypatch):
    if cinema == '1074':
        add_arkadia(engine)
    plan(engine, NOW, cinema_id=cinema)
    job = claim(engine, NOW)
    assert finish(engine, job, result('network_error'), NOW+1000)
    assert claim(engine, NOW+30_000) is None
    path = tmp_path/'seats.sqlite3'
    waiting = render(report(path, NOW+2000))
    assert 'Retry waiting until:' in waiting and '| RETRY' in waiting
    restarted = database_engine(path, readonly=False)
    try:
        # Planner refresh cannot reset eligibility or create another job.
        plan(restarted, NOW+30_000, cinema_id=cinema)
        retry = claim(restarted, NOW+31_000)
        assert retry['id'] == job['id'] and retry['claim_token'] != job['claim_token']
        assert finish(restarted, retry, result('success'), NOW+32_000)
        assert not finish(restarted, job, result('timeout'), NOW+32_001)
        assert claim(restarted, NOW+40_000) is None
    finally:
        restarted.dispose()
    data = report(path, NOW+3*MINUTE)
    assert data['seats']['successful_jobs'] == 1
    assert data['seats']['windows_finished'] == 1
    assert data['seats']['attempt_outcomes'] == {'network_error':1, 'success':1}
    assert data['seats']['max_start_delay_seconds'] == 31
    assert 'retry of the same job' in render(data)
    assert 'this window recovered via retry' in render(data)
    original = alerts.report
    monkeypatch.setattr(alerts, 'report', lambda *a, **k: {**original(*a, **k), 'issues': []})
    messages = []
    monkeypatch.setattr(alerts, 'send_telegram', lambda msg, cfg: (messages.append(msg) or True, None))
    alerts.evaluate_alerts(path, NOW+3*MINUTE, Settings())
    alerts.evaluate_alerts(path, NOW+4*MINUTE, Settings())
    assert len(messages) == 1 and 'recovered via retry' in messages[0]


def test_second_failure_does_not_retry_again(engine):
    plan(engine, NOW)
    job = claim(engine, NOW)
    finish(engine, job, result('timeout'), NOW+1)
    retry = claim(engine, NOW+30_001)
    finish(engine, retry, result('network_error'), NOW+30_002)
    assert claim(engine, NOW+61_000) is None
    with engine.connect() as db:
        assert db.execute(text('SELECT count(*) FROM seat_observations')).scalar_one() == 2
        assert db.execute(text('SELECT state FROM seat_jobs WHERE id=:id'), {'id':job['id']}).scalar_one() == 'done'


@pytest.mark.parametrize('outcome', ['blocked', 'tls_error', 'invalid_data', 'closed', 'upstream_error', 'success'])
def test_non_transient_results_are_never_retried(engine, outcome):
    plan(engine, NOW)
    finish(engine, claim(engine, NOW), result(outcome), NOW+1)
    assert claim(engine, NOW+31_000) is None


@pytest.mark.parametrize('cinema,finish_delay', [('kinoteka',71_000),('1074',31_000)])
def test_insufficient_remaining_budget_does_not_schedule_retry(engine, cinema, finish_delay):
    if cinema == '1074':
        add_arkadia(engine)
    plan(engine, NOW, cinema_id=cinema)
    job = claim(engine, NOW)
    finish(engine, job, result('timeout'), NOW+finish_delay)
    with engine.connect() as db:
        assert db.execute(text('SELECT retry_at_ms FROM seat_jobs WHERE id=:id'), {'id':job['id']}).scalar_one() is None


def test_queued_retry_expiry_preserves_failure_not_false_miss(engine, tmp_path):
    add_arkadia(engine)
    plan(engine, NOW, cinema_id='1074')
    job = claim(engine, NOW)
    finish(engine, job, result('network_error'), NOW+1)
    # Worker returns too late to leave the three-request budget; no request sent.
    assert claim(engine, NOW+61_000) is None
    data = report(tmp_path/'seats.sqlite3', NOW+3*MINUTE)
    assert data['seats']['missed'] == 0
    assert data['seats']['successful_jobs'] == 0
    assert data['seats']['attempt_outcomes'] == {'network_error':1}
    assert 'Retry not attempted:' in render(data)


def test_late_retry_counts_do_not_inflate_coverage(engine, tmp_path):
    plan(engine, NOW)
    finish(engine, claim(engine, NOW), result('timeout'), NOW+1)
    retry = claim(engine, NOW+31_000)
    finish(engine, retry, result('success'), NOW+121_000)
    data = report(tmp_path/'seats.sqlite3', NOW+3*MINUTE)
    assert data['seats']['successful_jobs'] == 0
    assert data['seats']['attempt_outcomes']['deadline_exceeded'] == 1
    assert data['evidence']['recent_attempts'][0]['available'] is None


def test_diagnostic_does_not_schedule_retry(engine):
    plan(engine, NOW, diagnostic=True)
    finish(engine, claim(engine, NOW, diagnostic_only=True), result('timeout'), NOW+1)
    assert claim(engine, NOW+31_000) is None


def test_waiting_retry_does_not_block_other_venue_and_cooldown_is_honored(engine):
    add_arkadia(engine)
    plan(engine, NOW)
    first = claim(engine, NOW)
    finish(engine, first, result('network_error'), NOW+1)
    other = claim(engine, NOW+3000)
    assert other['cinema_id'] != first['cinema_id']
    finish(engine, other, result('success'), NOW+3001)
    with engine.begin() as db:
        db.execute(text('UPDATE seat_provider_status SET cooldown_until_ms=:until WHERE provider=:provider'),
                   {'until': NOW+15*MINUTE, 'provider':first['provider']})
    assert claim(engine, NOW+31_000) is None


@pytest.mark.parametrize('cinema', ['kinoteka', '1074'])
def test_certificate_errors_are_classified_without_retry(cinema):
    import ssl
    import httpx
    from cinema_agg.server.seat_pilot import probe
    from test_seat_pilot import CINEMA, EVENT
    job = dict(provider='kinoteka', provider_cinema=CINEMA, cinema_event=EVENT)
    if cinema == '1074':
        job = dict(provider='cinema_city', cinema_id='1074', provider_cinema='1074', cinema_event='12345')
    def handler(request):
        raise httpx.ConnectError('sanitized') from ssl.SSLCertVerificationError('certificate failed')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe(client,job)['outcome'] == 'tls_error'


@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_transient_http_failure_retries_once_and_recovers(engine, status):
    add_arkadia(engine)
    plan(engine, NOW, cinema_id='1074')
    job = claim(engine, NOW)
    failure = {**result('upstream_error'), 'http_status': status}
    finish(engine, job, failure, NOW+1000)
    assert failure['retry_scheduled'] is True
    assert claim(engine, NOW+30_000) is None
    retry = claim(engine, NOW+31_000)
    assert retry['id'] == job['id']
    finish(engine, retry, result('success'), NOW+32_000)
    with engine.connect() as db:
        assert db.execute(text('SELECT count(*) FROM seat_observations WHERE job_id=:id'), {'id':job['id']}).scalar_one() == 2
        assert db.execute(text('SELECT state FROM seat_jobs WHERE id=:id'), {'id':job['id']}).scalar_one() == 'done'


@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 501, 505])
def test_other_http_errors_do_not_retry(engine, status):
    plan(engine, NOW)
    failure = {**result('upstream_error'), 'http_status': status}
    finish(engine, claim(engine, NOW), failure, NOW+1)
    assert failure['retry_scheduled'] is False
