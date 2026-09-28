import asyncio
import importlib
import socket
from unittest.mock import patch

import pytest
from pytest_socket import SocketConnectBlockedError

from cinema_agg import config
from cinema_agg.build import PosterService


def test_optional_poster_key_is_read_from_environment():
    try:
        with patch.dict('os.environ', {}, clear=True):
            importlib.reload(config)
            assert config.TMDB_API_KEY == ''
        with patch.dict('os.environ', {'TMDB_API_KEY': ' placeholder '}):
            importlib.reload(config)
            assert config.TMDB_API_KEY == 'placeholder'  # pragma: allowlist secret -- dummy test value
    finally:
        importlib.reload(config)


def test_missing_key_preserves_cached_posters_without_http(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    service = PosterService('')
    service.cache['cached'] = 'https://example.invalid/poster.jpg'

    async def check():
        with patch('httpx.AsyncClient', side_effect=AssertionError('Unexpected HTTP')):
            assert await service.get_poster('missing', 'Missing') is None
            assert await service.get_poster('cached', 'Cached') == service.cache['cached']

    asyncio.run(check())


def test_external_connections_are_blocked_by_the_test_suite():
    # Reserved documentation IP; pytest-socket must reject before any connection.
    with socket.socket() as connection:
        with pytest.raises(SocketConnectBlockedError):
            connection.connect(('192.0.2.1', 443))
