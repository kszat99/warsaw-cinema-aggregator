"""Fresh MSI session, hidden-state handshake only; never selects seats."""

import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .seat_providers import transport_outcome

ORIGIN = "https://wisla.novekino.pl"


class CutoffExpired(Exception):
    """Do not continue a final observation after the screening starts."""


def event_identity(url: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    ids = query.get("event_id", [])
    if (
        parts.scheme != "https"
        or parts.netloc != "wisla.novekino.pl"
        or parts.path not in {"/MSI/OrderTickets.aspx", "/MSI/Default.aspx"}
        or len(ids) != 1
        or not re.fullmatch(r"[0-9]{1,12}", ids[0])
    ):
        raise ValueError("Unapproved Wisla booking identity")
    return ids[0]


def request(
    client: httpx.Client,
    method: str,
    url: str,
    finish_before_ms: int | None = None,
    **kwargs: Any,
) -> httpx.Response:
    for _ in range(2):
        if not url.startswith(ORIGIN + "/MSI/"):
            raise ValueError("Unapproved redirect")
        remaining = (
            10.0
            if finish_before_ms is None
            else (finish_before_ms / 1000 - time.time())
        )
        if remaining <= 0:
            raise CutoffExpired
        response = client.request(
            method, url, follow_redirects=False, timeout=min(10, remaining), **kwargs
        )
        if finish_before_ms is not None and time.time() * 1000 >= finish_before_ms:
            raise CutoffExpired
        if response.status_code not in {301, 302, 303}:
            response.raise_for_status()
            return response
        url = str(response.url.join(response.headers["location"]))
        method, kwargs = "GET", {}
    raise ValueError("Redirect limit")


def parse(response: httpx.Response) -> dict[str, Any]:
    if response.url.path != "/MSI/OrderTickets.aspx":
        raise ValueError("Seat page unavailable; closure not established")
    soup = BeautifulSoup(response.text, "lxml")
    text = soup.get_text(" ", strip=True)
    total = re.search(r"Miejsc\s+łącznie\s*:\s*(\d+)", text, re.I)
    free = re.search(r"Dostępnych\s+miejsc\s*:\s*(\d+)", text, re.I)
    if not total or not free:
        raise ValueError("Missing capacity markers")
    capacity, available = int(total[1]), int(free[1])
    seats = soup.select('input[type="checkbox"][id*="seatCheckbox"]')
    ids = [seat.get("id") for seat in seats]
    if (
        not 0 < capacity <= 5000
        or not 0 <= available <= capacity
        or len(ids) != len(set(ids))
        or any(seat.has_attr("disabled") for seat in seats)
    ):
        raise ValueError("Seat counts disagree")
    diagnostics = None
    if len(seats) != available:
        # MSI's published availability includes seats absent from its selectable list.
        # Accept its explicit counter only with independent hall-capacity corroboration.
        hall = soup.select_one("#SeatCount")
        if (
            hall is None
            or str(hall.get("value")) != str(capacity)
            or not 0 < len(seats) < available
        ):
            raise ValueError("Seat counts disagree")
        diagnostics = dict(
            phase="seat_map",
            reason="provider_counter_differs_from_controls",
            count_source="published_availability",
            available_controls=len(seats),
            published_available=available,
            corroborated_capacity=capacity,
        )
    return dict(
        diagnostics=diagnostics,
        outcome="success",
        available=available,
        unavailable=capacity - available,
        capacity=capacity,
    )


def probe(
    client: httpx.Client,
    event: str,
    start_ms: int,
    *,
    finish_before_ms: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = dict(
        available=None, unavailable=None, capacity=None, http_status=None, cooldown_ms=0
    )
    client.cookies.clear()
    phase = "identity"
    last_response = None
    try:
        if not re.fullmatch(r"[0-9]{1,12}", event):
            raise ValueError("Invalid event")
        day = datetime.fromtimestamp(start_ms / 1000, ZoneInfo("Europe/Warsaw")).date()
        repertoire = (
            ORIGIN
            + "/MSI/mvc/pl?"
            + urlencode(dict(sort="Date", date=day.isoformat(), datestart="0"))
        )
        entry = (
            ORIGIN
            + "/MSI/Default.aspx?"
            + urlencode(
                dict(
                    event_id=event,
                    typetran="0",
                    returnlink="~/mvc/pl?sort=Date&date=" + day.isoformat(),
                )
            )
        )
        phase = "repertoire"
        last_response = request(
            client, "GET", repertoire, finish_before_ms=finish_before_ms
        )
        phase = "handshake"
        landing = request(
            client,
            "GET",
            entry,
            headers={"Referer": repertoire},
            finish_before_ms=finish_before_ms,
        )
        last_response = landing
        soup = BeautifulSoup(landing.text, "lxml")
        values = {
            str(n["name"]): str(n.get("value", ""))
            for n in soup.select('form input[type="hidden"][name]')
        }
        # Restrict the POST to framework state; never echo seat/payment controls.
        values = {
            k: v
            for k, v in values.items()
            if k.startswith("__") or k.endswith("hfldUniqueTabGuid")
        }
        random = soup.select_one("#randomWindowName")
        field = next((k for k in values if k.endswith("hfldUniqueTabGuid")), None)
        if random is None or not random.get("value") or field is None:
            raise ValueError("Session handshake unavailable")
        values[field] = str(random["value"])
        phase = "seat_map"
        response = request(
            client,
            "POST",
            entry,
            data=values,
            headers={"Referer": str(landing.url)},
            finish_before_ms=finish_before_ms,
        )
        last_response = response
        result["http_status"] = response.status_code
        result.update(parse(response))
    except CutoffExpired:
        result["outcome"] = "deadline_exceeded"
    except httpx.HTTPStatusError as exc:
        last_response = exc.response
        status = exc.response.status_code
        result.update(
            http_status=status,
            outcome="blocked" if status in {403, 429} else "http_error",
        )
        if status in {403, 429}:
            retry = exc.response.headers.get("Retry-After", "")
            result["cooldown_ms"] = max(
                900000, int(retry) * 1000 if retry.isdigit() else 0
            )
    except httpx.TimeoutException:
        result["outcome"] = "timeout"
    except httpx.HTTPError as exc:
        result["outcome"] = transport_outcome(exc)
    except (ValueError, KeyError, TypeError) as exc:
        result["outcome"] = "invalid_data"
        result["diagnostics"] = {"phase": phase, "reason": str(exc)[:200]}
    finally:
        if result.get("outcome") != "success" and last_response is not None:
            soup = BeautifulSoup(last_response.text, "lxml")
            for node in soup.select("script, style, input, textarea"):
                node.decompose()
            available_controls = len(
                BeautifulSoup(last_response.text, "lxml").select(
                    'input[type="checkbox"][id*="seatCheckbox"]'
                )
            )
            visible = soup.get_text(" ", strip=True)
            details = result.setdefault("diagnostics", {})
            details.update(
                phase=phase,
                path=last_response.url.path,
                response_text=visible[:24000],
                response_text_truncated=len(visible) > 24000,
                response_bytes=len(last_response.content),
                available_controls=available_controls,
            )
            for key, pattern in (
                ("published_available", r"Dostępnych\s+miejsc\s*:\s*(\d+)"),
                ("published_capacity", r"Miejsc\s+łącznie\s*:\s*(\d+)"),
            ):
                marker = re.search(pattern, visible, re.I)
                if marker:
                    details[key] = int(marker[1])
            result["http_status"] = result["http_status"] or last_response.status_code
        client.cookies.clear()
    return result
