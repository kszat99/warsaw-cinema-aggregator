import unittest
from datetime import date
from urllib.parse import parse_qs

import httpx

from cinema_agg.seat_availability import (
    SeatAvailabilityError,
    fetch_atlantic_seat_availability,
)


class AtlanticSeatAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_initializes_session_and_counts_available_seats(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/MSI/mvc/pl":
                return httpx.Response(200, text="repertoire")
            if request.method == "GET" and request.url.path == "/MSI/Default.aspx":
                return httpx.Response(
                    200,
                    text="""
                    <form>
                      <input type="hidden" name="__VIEWSTATE" value="state">
                      <input type="hidden" id="randomWindowName" name="randomWindowName" value="tab-123">
                      <input type="hidden" name="ctl00$ContentMain$hfldUniqueTabGuid" value="">
                    </form>
                    """,
                )
            if request.method == "POST" and request.url.path == "/MSI/Default.aspx":
                values = parse_qs(request.content.decode())
                self.assertEqual(values["ctl00$ContentMain$hfldUniqueTabGuid"], ["tab-123"])
                self.assertFalse(any("seatCheckbox" in name for name in values))
                return httpx.Response(
                    302,
                    headers={"Location": "/MSI/OrderTickets.aspx?event_id=47749&typetran=0"},
                )
            if request.url.path == "/MSI/OrderTickets.aspx":
                return httpx.Response(
                    200,
                    text="""
                    <div class="event-description"><h1>500 mil - napisy</h1></div>
                    <ul><li>Sala D</li></ul>
                    <input type="checkbox" id="seatCheckbox_1">
                    <input type="checkbox" id="seatCheckbox_2">
                    <input type="checkbox" id="seatCheckbox_3">
                    """,
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://atlantic.novekino.pl",
        ) as client:
            result = await fetch_atlantic_seat_availability(
                "https://atlantic.novekino.pl/MSI/OrderTickets.aspx?event_id=47749&typetran=1",
                date(2026, 9, 15),
                client,
            )

        self.assertEqual(result.event_id, "47749")
        self.assertEqual(result.title, "500 mil - napisy")
        self.assertEqual(result.hall, "Sala D")
        self.assertEqual(result.available, 3)
        self.assertEqual(result.capacity, 156)
        self.assertEqual(result.unavailable, 153)
        self.assertEqual(requests[0].url.params["date"], "2026-09-15")
        self.assertEqual(requests[1].url.path, "/MSI/Default.aspx")
        self.assertEqual(requests[1].url.params["typetran"], "0")

    async def test_rejects_page_without_session_handshake(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/MSI/mvc/pl":
                return httpx.Response(200, text="repertoire")
            return httpx.Response(200, text="<form></form>")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(SeatAvailabilityError, "handshake"):
                await fetch_atlantic_seat_availability(
                    "https://atlantic.novekino.pl/MSI/Default.aspx?event_id=1",
                    date(2026, 9, 15),
                    client,
                )

    async def test_zero_available_controls_is_a_valid_sold_out_map(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/MSI/mvc/pl":
                return httpx.Response(200, text="repertoire")
            if request.method == "GET" and request.url.path == "/MSI/Default.aspx":
                return httpx.Response(
                    200,
                    text="""
                    <form>
                      <input type="hidden" id="randomWindowName" name="randomWindowName" value="tab-1">
                      <input type="hidden" name="hfldUniqueTabGuid" value="">
                    </form>
                    """,
                )
            if request.method == "POST":
                return httpx.Response(
                    302,
                    headers={"Location": "/MSI/OrderTickets.aspx?event_id=2"},
                )
            return httpx.Response(
                200,
                text='<div class="event-description"><h1>Sold out</h1></div><p>Sala A</p>',
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await fetch_atlantic_seat_availability(
                "https://atlantic.novekino.pl/MSI/Default.aspx?event_id=2",
                date(2026, 9, 15),
                client,
            )

        self.assertEqual(result.available, 0)
        self.assertEqual(result.unavailable, 158)


if __name__ == "__main__":
    unittest.main()
