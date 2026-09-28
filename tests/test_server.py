import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cinema_agg.server.app import create_app
from cinema_agg.server.logging import JsonFormatter, logger
from cinema_agg.server.settings import Settings


@pytest.fixture
def events():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    yield stream
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def test_liveness_and_request_correlation(events):
    with TestClient(create_app()) as client:
        first = client.get('/health/live?token=private-test-value', headers={
            'Authorization': 'Bearer private-test-value',
            'X-Request-ID': 'untrusted-id',
        })
        second = client.get('/health/live')
        missing = client.get('/private-test-value')
    assert first.json() == {'status': 'ok'}
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'no-store'
    assert first.headers['x-request-id'] != second.headers['x-request-id']
    assert len(first.headers['x-request-id']) == 32
    assert missing.status_code == 404
    records = [json.loads(line) for line in events.getvalue().splitlines()]
    assert records[0]['event'] == 'api_started'
    assert records[-1]['event'] == 'api_stopped'
    assert records[1]['request_id'] == first.headers['x-request-id']
    assert records[1]['duration_ms'] >= 0
    assert 'private-test-value' not in events.getvalue()
    assert 'untrusted-id' not in events.getvalue()


def test_failure_is_generic_and_correlated(events):
    app = create_app()

    @app.get('/broken')
    async def broken():
        raise RuntimeError('private-test-value')

    with TestClient(app) as client:
        result = client.get('/broken')
    assert result.status_code == 500
    assert result.json() == {
        'detail': 'Internal server error', 'request_id': result.headers['x-request-id'],
    }
    records = [json.loads(line) for line in events.getvalue().splitlines()]
    failure = next(row for row in records if row['event'] == 'request_failed')
    assert failure['error_type'] == 'RuntimeError'
    assert failure['request_id'] == result.headers['x-request-id']
    assert 'private-test-value' not in result.text + events.getvalue()


@pytest.mark.parametrize('values', [
    {'host': '0.0.0.0'}, {'port': 0}, {'port': 65536}, {'unexpected': 'value'},
])
def test_invalid_settings(values):
    with pytest.raises(ValidationError):
        Settings.model_validate(values)


def test_environment_settings(monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith('CINEMA_API_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('CINEMA_API_PORT', '8123')
    assert Settings.from_environment().port == 8123
    monkeypatch.setenv('CINEMA_API_POTR', '8123')
    with pytest.raises(ValidationError):
        Settings.from_environment()


def test_invalid_configuration_does_not_echo_input(monkeypatch, capsys):
    from cinema_agg.server.__main__ import main

    monkeypatch.setenv('CINEMA_API_PORT', 'private-test-value')
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert 'CINEMA_API_PORT' in error
    assert 'private-test-value' not in error


def test_formatter_drops_unstructured_messages_and_tracebacks():
    record = logging.LogRecord('uvicorn.error', logging.ERROR, '', 0,
                               'private-test-value', (), None)
    assert 'private-test-value' not in JsonFormatter().format(record)
