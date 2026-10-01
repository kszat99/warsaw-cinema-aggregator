"""Read-only Amondo booking API; never substitute a nearby screening."""

import json
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .seat_providers import transport_outcome


def booking_identity(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    if (
        parts.scheme != "https"
        or parts.netloc not in {"biletomat.pl", "kicket.com"}
        or parts.path != "/embeddables/repertoire"
        or set(query) != {"organizerId", "showId"}
        or query.get("organizerId") != ["1772"]
        or len(query.get("showId", [])) != 1
        or not query["showId"][0].isdigit()
    ):
        raise ValueError("Unapproved Amondo booking identity")
    return "1772", query["showId"][0]


def probe(client: httpx.Client, show_id: str, starts_at_ms: int) -> dict[str, Any]:
    if not show_id.isdigit():
        raise ValueError("Invalid Amondo show ID")
    result: dict[str, Any] = dict(
        outcome="data_validation_error",
        available=None,
        unavailable=None,
        capacity=None,
        http_status=None,
        cooldown_ms=0,
    )
    details: dict[str, Any] = {"phase": "repertoire"}
    result["diagnostics"] = details

    def read(url: str, params: dict[str, Any] | None = None) -> Any:
        response = client.get(
            url,
            params=params,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )
        result["http_status"] = response.status_code
        details["returned_path"] = urlsplit(url).path
        if response.status_code in {403, 429}:
            retry = response.headers.get("Retry-After", "")
            result["cooldown_ms"] = (
                max(900_000, min(int(retry), 86400) * 1000)
                if retry.isdigit()
                else 900_000
            )
        response.raise_for_status()
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise ValueError("Unexpected status or oversized booking response")
        return response.json()

    try:
        events = read(
            "https://api.biletomat.pl/marketplace/repertoire",
            {"organizerId": "1772", "showId": show_id, "page": 0, "size": 100},
        )
        if not isinstance(events, list):
            raise ValueError("Unexpected repertoire structure")
        matches = []
        for event in events:
            start = datetime.fromisoformat(event["displayPeriod"]["startsAt"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=ZoneInfo("Europe/Warsaw"))
            if int(start.timestamp() * 1000) == starts_at_ms:
                matches.append(event)
        if not matches:
            result["outcome"] = "listing_absent"
            details["reason"] = (
                "Exact screening absent from Amondo repertoire; "
                "sales cutoff is not established"
            )
            return result
        if len(matches) != 1:
            raise ValueError("Ambiguous screening identity")
        event = matches[0]
        event_id = str(event["id"])
        if (
            not event_id.isdigit()
            or str(event["show"]["id"]) != show_id
            or str(event["organizer"]["id"]) != "1772"
        ):
            raise ValueError("Booking event identity mismatch")
        details["event_id"] = event_id
        details["phase"] = "sales_info"
        items = read("https://biletomat.pl/api-ui/salesInfo", {"events": event_id})
        if (
            not isinstance(items, list)
            or len(items) != 1
            or str(items[0]["eventId"]) != event_id
        ):
            raise ValueError("Sales response event mismatch")
        primary = items[0]["saleInfo"]["primarySale"]
        availability = primary["availability"]
        details["sales_status"] = str(availability.get("status", "unknown"))[:100]
        details["sales_stop_at"] = str(availability.get("stopDate", ""))[:60]
        if type(availability.get("available")) is not bool:
            raise ValueError("Missing explicit availability state")
        if availability["available"] is False:
            result["outcome"] = "sales_unavailable"
            details["reason"] = "Amondo explicitly reports ticket sales unavailable"
            details["sold_out"] = availability.get("soldOut") is True
            details["finished"] = availability.get("finished") is True
            return result
        places = primary["availablePlaces"]
        if not isinstance(places, list):
            raise ValueError("Invalid available places")
        numbered = [p for p in places if p["placeType"] == "NUMBERED"]
        if len({p["id"] for p in numbered}) != len(numbered):
            raise ValueError("Duplicate available seat identities")
        if any(
            type(p.get("remainingQuantity")) is not int
            or p["remainingQuantity"] not in {0, 1}
            for p in numbered
        ):
            raise ValueError("Invalid numbered seat quantities")
        available = sum(p["remainingQuantity"] for p in numbered)
        details["phase"] = "seat_map"
        layout = read(f"https://biletomat.pl/api-ui/seats-plan/{event_id}")
        schema = json.loads(layout["classicSeatsPlanData"]["schema"])
        svg = schema["image"].replace('\\"', '"')
        seats = BeautifulSoup(svg, "html.parser").select(
            '[data-type="place"][data-place]'
        )
        identities = {(seat.get("data-row"), seat["data-place"]) for seat in seats}
        capacity = len(seats)
        if (
            not 0 < capacity <= 5000
            or len(identities) != capacity
            or available > capacity
        ):
            raise ValueError("Invalid seat layout or availability exceeds capacity")
        result.update(
            outcome="success",
            available=available,
            unavailable=capacity - available,
            capacity=capacity,
        )
        details["count_source"] = "numbered availablePlaces and seat layout"
    except httpx.HTTPStatusError as error:
        result["outcome"] = (
            "blocked" if error.response.status_code in {403, 429} else "upstream_error"
        )
        details["reason"] = "Amondo booking API returned an HTTP error"
    except httpx.TimeoutException:
        result["outcome"] = "timeout"
        details["reason"] = "Amondo booking API timed out"
    except httpx.HTTPError as error:
        result["outcome"] = transport_outcome(error)
        details["reason"] = "Amondo booking API connection failed"
    except (ValueError, KeyError, TypeError, AttributeError):
        details["reason"] = (
            "Amondo response failed identity, structure or seat-count validation"
        )
    return result
