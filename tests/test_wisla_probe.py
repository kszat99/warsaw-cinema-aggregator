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


def test_final_probe_never_starts_after_cutoff(monkeypatch):
    monkeypatch.setattr("cinema_agg.server.wisla_probe.time.time", lambda: START / 1000)
    client, calls = client_for()
    with client:
        result = probe(client, "114926", START, finish_before_ms=START)
    assert result["outcome"] == "deadline_exceeded"
    assert not calls


def test_failure_evidence_excludes_framework_secrets():
    client, _ = client_for("handshake")
    with client:
        result = probe(client, "114926", START)
    assert result["http_status"] == 200
    assert result["diagnostics"]["phase"] == "handshake"
    assert result["diagnostics"]["response_text"] == "generic error"


def test_corroborated_published_counts_can_differ_from_selectable_controls():
    from cinema_agg.server.wisla_probe import parse

    response = httpx.Response(
        200,
        text=MAP.replace("miejsc: 2", "miejsc: 3")
        + '<input type="hidden" id="SeatCount" value="120">',
        request=httpx.Request("GET", ORIGIN + "/MSI/OrderTickets.aspx"),
    )
    result = parse(response)
    assert result["available"] == 3
    assert result["unavailable"] == 117
    assert result["diagnostics"]["available_controls"] == 2


def test_failure_evidence_strips_scripts_inputs_and_caps_text():
    def handler(request):
        return httpx.Response(
            200,
            text='<script>secret-cookie</script><input value="secret-state">'
            + "x" * 30000,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe(client, "114926", START)
    evidence = result["diagnostics"]["response_text"]
    assert "secret" not in evidence
    assert len(evidence) == 24000
    assert result["diagnostics"]["response_text_truncated"]


def test_atlantic_redirect_referer_and_capacity():
    from cinema_agg.server.wisla_probe import ATLANTIC_ORIGIN

    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "atlantic.novekino.pl"
        if request.url.path == "/MSI/mvc/pl":
            return httpx.Response(
                200,
                text='<a href="/MSI/Default.aspx?event_id=123&amp;typetran=0">Buy</a>',
            )
        if request.method == "POST":
            data = parse_qs(request.content.decode())
            assert data["ctl$hdnServer"] == ["framework-server"]
            assert "seatCheckboxBad" not in data
            return httpx.Response(
                302, headers={"Location": "/MSI/OrderTickets.aspx?event_id=123"}
            )
        if request.url.path == "/MSI/Default.aspx":
            return httpx.Response(
                200,
                text=LANDING.replace(
                    "</form>",
                    '<input type="hidden" name="ctl$hdnServer" value="framework-server"></form>',
                ),
            )
        assert request.headers["Referer"].startswith(
            ATLANTIC_ORIGIN + "/MSI/Default.aspx"
        )
        return httpx.Response(
            200, text='Sala A <input id="SeatCount" value="158">' + MAP
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe(client, "123", START, origin=ATLANTIC_ORIGIN)
    assert result["outcome"] == "success"
    assert (result["available"], result["capacity"]) == (
        2,
        120,
    )  # explicit labels take precedence
    assert len(calls) == 4


def test_atlantic_uses_corroborated_hall_capacity_without_labels():
    from cinema_agg.server.wisla_probe import parse, ATLANTIC_ORIGIN

    page = 'Sala A <input id="SeatCount" value="158"><input type="checkbox" id="seatCheckbox1">'
    response = httpx.Response(
        200,
        text=page,
        request=httpx.Request("GET", ATLANTIC_ORIGIN + "/MSI/OrderTickets.aspx"),
    )
    assert parse(response)["capacity"] == 158
    assert parse(response)["available"] == 1
    with pytest.raises(ValueError):
        parse(
            httpx.Response(
                200, text=page.replace("158", "159"), request=response.request
            )
        )


def test_atlantic_identity_is_separate_from_wisla():
    from cinema_agg.server.wisla_probe import ATLANTIC_ORIGIN

    url = ATLANTIC_ORIGIN + "/MSI/OrderTickets.aspx?event_id=123"
    assert event_identity(url, ATLANTIC_ORIGIN) == "123"
    with pytest.raises(ValueError):
        event_identity(url)
