from dataclasses import dataclass
from datetime import date, datetime
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup


ATLANTIC_HALL_CAPACITIES = {
    "A": 158,
    "B": 221,
    "C": 259,
    "D": 156,
}


class SeatAvailabilityError(RuntimeError):
    """Raised when a booking page cannot produce a trustworthy seat count."""


@dataclass(frozen=True)
class SeatAvailability:
    event_id: str
    title: str
    hall: str
    available: int
    capacity: int
    unavailable: int
    booking_url: str
    checked_at: datetime


def _atlantic_entry_url(booking_url: str) -> tuple[str, str]:
    parts = urlsplit(booking_url)
    if parts.hostname != "atlantic.novekino.pl":
        raise SeatAvailabilityError("The Atlantic probe only accepts atlantic.novekino.pl URLs")

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    event_id = query.get("event_id")
    if not event_id or not event_id.isdigit():
        raise SeatAvailabilityError("The booking URL has no numeric event_id")

    query["typetran"] = "0"
    path = re.sub(r"/(?:Default|OrderTickets)\.aspx$", "/Default.aspx", parts.path)
    if path == parts.path and not parts.path.endswith("/Default.aspx"):
        raise SeatAvailabilityError("The booking URL is not an MSI ticket URL")

    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), "")), event_id


def _hidden_form_values(soup: BeautifulSoup) -> dict[str, str]:
    values = {
        node["name"]: node.get("value", "")
        for node in soup.select('form input[type="hidden"][name]')
    }
    random_name = soup.select_one("#randomWindowName")
    unique_field = next(
        (name for name in values if name.endswith("hfldUniqueTabGuid")),
        None,
    )
    if random_name is None or not random_name.get("value") or unique_field is None:
        raise SeatAvailabilityError("Atlantic did not return its booking-session handshake")
    values[unique_field] = random_name["value"]
    return values


def _parse_atlantic_seat_map(response: httpx.Response, event_id: str) -> SeatAvailability:
    if not response.url.path.endswith("/MSI/OrderTickets.aspx"):
        raise SeatAvailabilityError(
            f"Atlantic did not open a seat map (ended at {response.url})"
        )

    soup = BeautifulSoup(response.text, "lxml")
    available = len(soup.select('input[type="checkbox"][id*="seatCheckbox"]'))

    page_text = soup.get_text(" ", strip=True)
    hall_match = re.search(r"\bSala\s+([A-D])\b", page_text, flags=re.IGNORECASE)
    if hall_match is None:
        raise SeatAvailabilityError("The seat map does not identify Atlantic's hall")
    hall_letter = hall_match.group(1).upper()
    capacity = ATLANTIC_HALL_CAPACITIES[hall_letter]
    if available > capacity:
        raise SeatAvailabilityError(
            f"Seat map exposes {available} seats, above Sala {hall_letter}'s capacity {capacity}"
        )

    title_node = soup.select_one(".event-description h1, h1")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    return SeatAvailability(
        event_id=event_id,
        title=title,
        hall=f"Sala {hall_letter}",
        available=available,
        capacity=capacity,
        unavailable=capacity - available,
        booking_url=str(response.url),
        checked_at=datetime.now().astimezone(),
    )


async def fetch_atlantic_seat_availability(
    booking_url: str,
    screening_date: date,
    client: httpx.AsyncClient,
) -> SeatAvailability:
    """Open Atlantic's read-only seat map and count available controls.

    Atlantic requires a repertoire visit followed by an ASP.NET tab/session
    handshake. The POST below contains only hidden form state; it does not send
    a seat identifier and therefore does not select or hold a seat.
    """
    entry_url, event_id = _atlantic_entry_url(booking_url)
    parts = urlsplit(entry_url)
    repertoire_url = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/MSI/mvc/pl",
            urlencode(
                {
                    "sort": "Date",
                    "date": screening_date.isoformat(),
                    "datestart": "0",
                }
            ),
            "",
        )
    )

    repertoire = await client.get(repertoire_url, follow_redirects=True)
    repertoire.raise_for_status()
    landing = await client.get(
        entry_url,
        headers={"Referer": str(repertoire.url)},
        follow_redirects=True,
    )
    landing.raise_for_status()
    form_values = _hidden_form_values(BeautifulSoup(landing.text, "lxml"))

    seat_map = await client.post(
        entry_url,
        data=form_values,
        headers={"Referer": str(landing.url)},
        follow_redirects=True,
    )
    seat_map.raise_for_status()
    return _parse_atlantic_seat_map(seat_map, event_id)
