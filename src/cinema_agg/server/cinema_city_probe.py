"""One-venue readiness probe; no scheduled collection or booking mutations."""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx

from .collector import WARSAW, make_fetch

ORIGIN = "https://tickets.cinema-city.pl"


def presentation_id(url: str) -> str:
    parts = urlsplit(url)
    match = re.fullmatch(r"/(?:api/)?order/(\d+)", parts.path)
    if parts.scheme != "https" or parts.netloc != "tickets.cinema-city.pl" or not match:
        raise ValueError("Unapproved booking URL")
    query = parse_qs(parts.query, keep_blank_values=True)
    if parts.fragment or (query and query not in ({"lang": ["pl"]}, {"lang": ["en"]})):
        raise ValueError("Unexpected booking parameters")
    return match[1]


def count_seats(node: Any) -> int:
    if isinstance(node, dict):
        seat = (
            "tg" in node and "n" in node and not any(k in node for k in ("G", "R", "S"))
        )
        return int(seat) + sum(count_seats(value) for value in node.values())
    if isinstance(node, list):
        return sum(count_seats(value) for value in node)
    return 0


def probe(client: httpx.Client, booking: str) -> dict[str, Any]:
    event = presentation_id(booking)
    headers = {
        "Accept": "application/json",
        "Origin": ORIGIN,
        "Referer": f"{ORIGIN}/order/{event}",
        "uuid": str(uuid4()),
    }
    step = "presentation"
    try:
        response = client.get(
            f"{ORIGIN}/api/presentations/{event}",
            headers=headers,
            follow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            error = data["error"]
            code = error.get("error") if isinstance(error, dict) else None
            return {
                "outcome": "closed" if code == "TICKETING_ENDED" else "upstream_error",
                "step": step,
            }
        presentation = data["presentation"]
        if presentation.get("isTicketingAllowedDuringSaleWindow") is False:
            return {"outcome": "closed", "step": step}

        def identifier(key: str) -> str:
            value = presentation[key]
            if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
                raise ValueError("Invalid identifier")
            return str(value)

        venue, plan, venue_type = (
            identifier(k) for k in ("venueId", "seatplanId", "venueTypeId")
        )
        reserved = presentation.get("isReserved")
        if type(reserved) is not bool:
            raise ValueError("Missing reservation metadata")
        step = "seatplan"
        # This POST reads layout only; no seat selection or reservation endpoint.
        response = client.post(
            f"{ORIGIN}/api/seats/seatplanV2",
            params={"venueId": venue, "seatplanId": plan},
            json={},
            headers=headers,
            follow_redirects=False,
        )
        response.raise_for_status()
        capacity = count_seats(response.json())
        step = "seat_status"
        response = client.get(
            f"{ORIGIN}/api/seats/seats-statusV2",
            params={
                "presentationId": event,
                "venueTypeId": venue_type,
                "isReserved": int(reserved),
            },
            headers=headers,
            follow_redirects=False,
        )
        response.raise_for_status()
        seats = response.json()["seats"]
        if (
            not isinstance(seats, dict)
            or not 0 < capacity <= 5000
            or len(seats) != capacity
            or any(type(v) is not int or v < 0 for v in seats.values())
        ):
            return {
                "outcome": "invalid_data",
                "step": step,
                "layout_capacity": capacity,
                "status_count": len(seats) if isinstance(seats, dict) else None,
            }
        free = sum(v == 0 for v in seats.values())
        return {
            "outcome": "success",
            "available": free,
            "unavailable": capacity - free,
            "capacity": capacity,
            "presentation_id": event,
        }
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        return {
            "outcome": "blocked" if status in {403, 429} else "upstream_error",
            "step": step,
            "http_status": status,
        }
    except httpx.TimeoutException:
        return {"outcome": "timeout", "step": step}
    except httpx.HTTPError:
        return {"outcome": "network_error", "step": step}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"outcome": "invalid_data", "step": step}


def local_start(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=WARSAW)
        if value.tzinfo is None
        else value.astimezone(WARSAW)
    )


async def readiness() -> dict[str, Any]:
    now = datetime.now(WARSAW)
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}
    ) as client:
        fetch = make_fetch(client)
        # One date/venue; use tomorrow to ensure time for operator verification.
        rows = await fetch("1074", (now + timedelta(days=1)).date())
    future = [
        r
        for r in rows
        if local_start(r.starts_at) > now + timedelta(minutes=30) and r.booking_url
    ]
    if not future:
        return {"outcome": "no_target", "screenings_fetched": len(rows)}
    target = min(future, key=lambda r: r.starts_at)
    with httpx.Client(timeout=20) as client:
        result = probe(client, target.booking_url or "")
    return {
        "cinema": "Cinema City Arkadia",
        "screenings_fetched": len(rows),
        "title": target.title_raw,
        "starts_at": local_start(target.starts_at).isoformat(),
        "booking_url": target.booking_url,
        **result,
    }


def main() -> None:
    try:
        result = asyncio.run(readiness())
    except Exception as error:
        print(
            json.dumps({"outcome": "probe_failed", "error_type": type(error).__name__})
        )
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=True))
    if result["outcome"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
