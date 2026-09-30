from urllib.parse import parse_qs

import httpx
import pytest

from cinema_agg.server.wisla_probe import ORIGIN, event_identity, probe

START = 1790841600000
LANDING = """<form><input type="hidden" name="__VIEWSTATE" value="state">
<input type="hidden" name="ctl$hfldUniqueTabGuid" value="">
<input type="hidden" name="seatCheckboxBad" value="not-for-post">
<input id="randomWindowName" value="tab"></form>"""
MAP = """Miejsc łącznie: 120 Dostępnych miejsc: 2
<input type="checkbox" id="seatCheckbox1"><input type="checkbox" id="seatCheckbox2">"""


def client_for(mode="ok"):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "wisla.novekino.pl"
        if request.url.path == "/MSI/mvc/pl":
            return httpx.Response(200, text="repertoire")
        if request.method == "POST":
            values = parse_qs(request.content.decode())
            assert set(values) == {"__VIEWSTATE", "ctl$hfldUniqueTabGuid"}
            assert values["ctl$hfldUniqueTabGuid"] == ["tab"]
            return httpx.Response(
                302,
                headers={
                    "Location": "https://example.org/other"
                    if mode == "redirect"
                    else "/MSI/OrderTickets.aspx"
                },
            )
        if request.url.path == "/MSI/Default.aspx":
            assert request.url.params["returnlink"].endswith("date=2026-10-01")
            if mode == "blocked":
                return httpx.Response(429, headers={"Retry-After": "1200"})
            return httpx.Response(
                200, text="generic error" if mode == "handshake" else LANDING
            )
        return httpx.Response(
            200,
            text=MAP.replace("miejsc: 2", "miejsc: 3") if mode == "mismatch" else MAP,
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_fresh_handshake_and_count_validation():
    client, calls = client_for()
    with client:
        result = probe(client, "114926", START)
    assert result["outcome"] == "success"
    assert (result["available"], result["unavailable"], result["capacity"]) == (
        2,
        118,
        120,
    )
    assert len(calls) == 4


@pytest.mark.parametrize("mode", ["handshake", "mismatch", "redirect"])
def test_technical_failure_is_never_closed_or_zero(mode):
    client, _ = client_for(mode)
    with client:
        result = probe(client, "114926", START)
    assert result["outcome"] == "invalid_data"
    assert result["available"] is None


def test_blocked_respects_retry_after():
    client, calls = client_for("blocked")
    with client:
        result = probe(client, "114926", START)
    assert result["outcome"] == "blocked"
    assert result["cooldown_ms"] == 1200000
    assert len(calls) == 2


def test_identity_rejects_other_hosts_and_duplicate_events():
    assert event_identity(ORIGIN + "/MSI/OrderTickets.aspx?event_id=123") == "123"
    for url in (
        "https://example.org/MSI/OrderTickets.aspx?event_id=123",
        ORIGIN + "/MSI/OrderTickets.aspx?event_id=123&event_id=456",
    ):
        with pytest.raises(ValueError):
            event_identity(url)
