import httpx
import pytest

from cinema_agg.server.cinema_city_probe import probe, presentation_id

URL = 'https://tickets.cinema-city.pl/order/12345'


def test_missing_event_reports_provider_code_not_http_failure():
    with httpx.Client(transport=httpx.MockTransport(lambda request:
        httpx.Response(200,json={'error':{'error':'PRESENTATION_NOT_FOUND'}}))) as c:
        result=probe(c,URL)
    assert result['outcome']=='screening_missing'
    assert result['http_status']==200
    assert result['diagnostics']['provider_code']=='PRESENTATION_NOT_FOUND'
    assert result['diagnostics']['booking_url']==URL+'?lang=pl'


def client(statuses=None, code=200, reserved=1, event=12345):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers['User-Agent'] == 'Mozilla/5.0'
        assert request.headers['uuid'] == requests[0].headers['uuid']
        if len(requests) == 1:
            return httpx.Response(code, json={'presentation': {
                'id':event, 'venueId':1074, 'seatplanId':10, 'venueTypeId':1,
                'isReserved':reserved, 'isTicketingAllowedDuringSaleWindow':True}})
        if 'seatplanV2' in request.url.path:
            assert request.method == 'POST'
            return httpx.Response(200, json={'S':{'1':{'G':{'1':{'R':{'1':{'S':{'1':{'tg':1,'n':'A1'},'2':{'tg':1,'n':'A2'}}}}}}}}})
        return httpx.Response(200, json={'seats': statuses if statuses is not None else {'1_1_1':0}})
    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_counts_and_read_only_endpoint_sequence():
    c, requests = client()
    with c:
        result = probe(c, URL)
    assert result['outcome'] == 'success'
    assert (result['available'],result['unavailable'],result['capacity']) == (1,1,2)
    assert len(requests) == 3


@pytest.mark.parametrize('statuses', [{'unknown':0}, {'1_1_1':True}, {'1_1_1':-1}, {'1_1_1':None}])
def test_invalid_metadata_or_coordinates_are_unknown(statuses):
    c, _ = client(statuses)
    with c:
        result = probe(c, URL)
    assert result['outcome'] == 'invalid_data'
    assert 'available' not in result


@pytest.mark.parametrize('statuses,available', [({}, 0), ({'1_1_1': 2}, 1), ({'1_1_1': '1,2', '1_2_1': '0'}, 2)])
def test_sparse_status_keys_are_available_regardless_of_ticket_metadata(statuses, available):
    c, _ = client(statuses)
    with c:
        result = probe(c, URL)
    assert result['outcome'] == 'success'
    assert result['available'] == available
    assert result['unavailable'] == 2 - available


@pytest.mark.parametrize('reserved', [True, False, 0, 1])
def test_boolean_and_integer_reservation_metadata(reserved):
    c, _ = client(reserved=reserved)
    with c:
        assert probe(c, URL)['outcome'] == 'success'


def test_wrong_presentation_stops_before_seat_requests():
    c, requests = client(event=999)
    with c:
        assert probe(c, URL)['outcome'] == 'invalid_data'
    assert len(requests) == 1


@pytest.mark.parametrize('code,outcome', [(403,'blocked'),(429,'blocked'),(404,'upstream_error')])
def test_http_failures_are_not_sales_closure(code,outcome):
    c, requests = client(code=code)
    with c:
        assert probe(c,URL)['outcome'] == outcome
    assert len(requests) == 1


def test_url_allowlist():
    assert presentation_id(URL+'?lang=pl') == '12345'
    with pytest.raises(ValueError):
        presentation_id('https://example.com/order/12345')


def test_readiness_uses_catalog_id_and_normalizes_local_times(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from cinema_agg.server import cinema_city_probe as module
    seen = []
    async def fetch(cinema, day):
        seen.append(cinema)
        return [SimpleNamespace(starts_at=datetime.now()+timedelta(days=1),
            booking_url=URL+'?lang=pl', title_raw='Test')]
    monkeypatch.setattr(module,'make_fetch',lambda c: fetch)
    monkeypatch.setattr(module,'probe',lambda *a: {'outcome':'success'})
    result=asyncio.run(module.readiness())
    assert seen == ['1074']
    assert result['outcome']=='success'
    assert '+' in result['starts_at']
