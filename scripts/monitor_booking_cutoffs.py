import argparse
import asyncio
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup


CSV_FIELDS = [
    "checked_at_warsaw",
    "cinema_id",
    "cinema",
    "platform",
    "film",
    "screening_start_warsaw",
    "minutes_from_start",
    "state",
    "available",
    "capacity",
    "unavailable",
    "advertised_sale_time_to",
    "duration_ms",
    "detail",
    "booking_url",
]

ATLANTIC_CAPACITIES = {"A": 158, "B": 221, "C": 259, "D": 156}
CLOSED_WORDS = (
    "sprzedaż internetowa zakończona",
    "sprzedaz internetowa zakonczona",
    "sales ended",
    "sale has ended",
    "session expired",
)

# bilety24 inline seat-map: seats with object_status 0 = available, 1 = taken.
# Only rows with object_type == "seat" are real seats (row-label pseudo-elements have type "rowName").
# The array is assigned as:  seats = [{...}, ...];
# We look for the first assignment that contains "object_type" to skip small jQuery variable refs.
_B24_SEATS_RE = re.compile(r'\bseats\s*=\s*(\[\s*\{"object_type".*?\])\s*;', re.DOTALL)


@dataclass
class Target:
    cinema_id: str
    cinema: str
    platform: str
    film: str
    screening_start: datetime
    booking_url: str
    verify_ssl: bool = True
    advertised_sale_time_to: str = ""


@dataclass
class Result:
    state: str
    available: Optional[int] = None
    capacity: Optional[int] = None
    detail: str = ""

    @property
    def unavailable(self) -> Optional[int]:
        if self.available is None or self.capacity is None:
            return None
        return self.capacity - self.available


def parse_rendered_seat_map(platform: str, html: str) -> Result:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True).lower()
    closed_text = next((phrase for phrase in CLOSED_WORDS if phrase in text), None)
    if closed_text:
        return Result("closed", detail=f"page says: {closed_text}")

    if platform == "cinema_city":
        seats = soup.select(".seat-hit-area")
        available = soup.select("g:has(.seat-hit-area) use.s.a")
        if seats:
            return Result("open", len(available), len(seats), "rendered Cinema City seat map")
    elif platform == "multikino":
        seats = soup.select("button.seats__seat[data-seat-status]")
        if seats:
            available = sum(
                not seat.get("data-seat-status", "").startswith("1-") for seat in seats
            )
            return Result("open", available, len(seats), "rendered Multikino seat map")
    elif platform == "helios":
        placeholders = soup.select(".screen-placeholder.is-seat")
        if placeholders:
            capacity = sum(
                int(match.group(1)) if (match := re.search(r"size-placeholder-(\d+)", " ".join(node.get("class", [])))) else 1
                for node in placeholders
            )
            available = len(soup.select(".seat.free"))
            return Result("open", available, capacity, "rendered Helios seat map")
    elif platform == "amondo":
        seats = soup.select('[data-type="place"][data-place]')
        if seats:
            return Result("open", capacity=len(seats), detail="rendered Amondo seat map")

    return Result("closed", detail="no usable seat-map elements after rendering")


class CutoffMonitor:
    def __init__(self, chrome_path: Path, work_dir: Path):
        self.chrome_path = chrome_path
        self.work_dir = work_dir
        self.http_clients: dict[str, httpx.Client] = {}
        self.msi_seat_urls: dict[str, str] = {}

    def close(self) -> None:
        for client in self.http_clients.values():
            client.close()

    def _client(self, target: Target) -> httpx.Client:
        if target.cinema_id not in self.http_clients:
            self.http_clients[target.cinema_id] = httpx.Client(
                timeout=30,
                follow_redirects=True,
                verify=target.verify_ssl,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        return self.http_clients[target.cinema_id]

    def probe(self, target: Target) -> Result:
        if target.platform == "msi":
            return self._probe_msi(target)
        if target.platform == "kinoteka":
            return self._probe_kinoteka(target)
        if target.platform == "bilety24":
            return self._probe_bilety24(target)
        if target.platform == "cinema_city":
            return self._probe_cinema_city(target)
        if target.platform == "amondo":
            return self._probe_amondo(target)
        return self._probe_rendered(target)

    def _probe_kinoteka(self, target: Target) -> Result:
        parts = urlsplit(target.booking_url)
        query = parts.query
        if not query and "?" in parts.fragment:
            query = parts.fragment.split("?", 1)[1]
        params = dict(parse_qsl(query))
        screening_id = params["screeningId"]
        cinema_id = params["cinemaId"]
        url = f"https://restapi.kinoteka.pl/api/cinema/{cinema_id}/screening/{screening_id}/occupancy"
        response = self._client(target).get(url)
        if response.status_code in {404, 409, 410}:
            return Result("closed", detail=f"occupancy endpoint returned HTTP {response.status_code}")
        response.raise_for_status()
        data = response.json()
        return Result(
            "open",
            available=data.get("seatsLeft"),
            capacity=(data.get("seatsLeft", 0) + data.get("totalOccupied", 0)),
            detail="Kinoteka occupancy endpoint",
        )

    def _probe_msi(self, target: Target) -> Result:
        client = self._client(target)
        cached_url = self.msi_seat_urls.get(target.cinema_id)
        if cached_url:
            response = client.get(cached_url)
            if response.url.path.endswith("/MSI/OrderTickets.aspx"):
                parsed = self._parse_msi(response)
                if parsed.state == "open":
                    return parsed

        parts = urlsplit(target.booking_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["typetran"] = "0"
        entry_path = re.sub(r"/(?:Default|OrderTickets)\.aspx$", "/Default.aspx", parts.path)
        entry_url = urlunsplit((parts.scheme, parts.netloc, entry_path, urlencode(query), ""))
        repertoire_url = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                "/MSI/mvc/pl",
                urlencode({"sort": "Date", "date": target.screening_start.date().isoformat(), "datestart": "0"}),
                "",
            )
        )
        repertoire = client.get(repertoire_url)
        repertoire.raise_for_status()
        landing = client.get(entry_url, headers={"Referer": str(repertoire.url)})
        landing.raise_for_status()
        soup = BeautifulSoup(landing.text, "lxml")
        values = {
            node["name"]: node.get("value", "")
            for node in soup.select('form input[type="hidden"][name]')
        }
        random_name = soup.select_one("#randomWindowName")
        unique_field = next((name for name in values if name.endswith("hfldUniqueTabGuid")), None)
        if random_name is None or not random_name.get("value") or unique_field is None:
            return Result("closed", detail=f"MSI handshake unavailable at {landing.url.path}")
        values[unique_field] = random_name["value"]
        response = client.post(entry_url, data=values, headers={"Referer": str(landing.url)})
        response.raise_for_status()
        if not response.url.path.endswith("/MSI/OrderTickets.aspx"):
            return Result("closed", detail=f"MSI ended at {response.url.path}")
        self.msi_seat_urls[target.cinema_id] = str(response.url)
        return self._parse_msi(response)

    @staticmethod
    def _parse_msi(response: httpx.Response) -> Result:
        soup = BeautifulSoup(response.text, "lxml")
        text = soup.get_text(" ", strip=True)
        available = len(soup.select('input[type="checkbox"][id*="seatCheckbox"]'))
        total_match = re.search(r"Miejsc\s+łącznie\s*:?\s*(\d+)", text, re.IGNORECASE)
        capacity = int(total_match.group(1)) if total_match else None
        if capacity is None and response.url.host == "atlantic.novekino.pl":
            hall = re.search(r"\bSala\s+([A-D])\b", text, re.IGNORECASE)
            capacity = ATLANTIC_CAPACITIES.get(hall.group(1).upper()) if hall else None
        if capacity is None:
            return Result("closed", detail="MSI seat page has no trustworthy capacity marker")
        return Result("open", available, capacity, "MSI seat map")

    def _probe_bilety24(self, target: Target) -> Result:
        """Parse the inline ``seats = [...]`` JSON array that bilety24 embeds directly
        in the booking page HTML.  No JavaScript rendering required.

        Each element has ``object_type`` (``"seat"`` | ``"rowName"``),
        ``object_status`` (``0`` = available, ``1`` = taken / reserved), and
        ``object_active`` (``"1"`` if the seat exists in the hall layout).
        """
        import json as _json

        response = self._client(target).get(target.booking_url)
        if response.status_code == 404:
            return Result("closed", detail="bilety24 returned HTTP 404")
        response.raise_for_status()

        text_lower = response.text.lower()
        closed_phrase = next((p for p in CLOSED_WORDS if p in text_lower), None)
        if closed_phrase:
            return Result("closed", detail=f"page says: {closed_phrase}")

        m = _B24_SEATS_RE.search(response.text)
        if not m:
            return Result("closed", detail="bilety24 page has no inline seat map (sales may have closed)")

        try:
            seats = _json.loads(m.group(1))
        except Exception as exc:
            return Result("error", detail=f"bilety24 seats JSON parse error: {exc}")

        real_seats = [s for s in seats if s.get("object_type") == "seat"]
        if not real_seats:
            return Result("closed", detail="bilety24 seat array is empty")

        capacity = len(real_seats)
        available = sum(1 for s in real_seats if str(s.get("object_status")) == "0")
        return Result("open", available, capacity, "bilety24 inline seat map")


    def _probe_cinema_city(self, target: Target) -> Result:
        """Read Cinema City's PresGlobal JSON endpoints directly.

        The rendered order page currently loads Cloudflare Turnstile and may show
        ``Błąd reCaptchy`` in headless Chrome before the seat map is hydrated.
        The app itself still calls these read-only JSON endpoints.  The seat
        status endpoint requires the same per-session ``uuid`` header that the
        Nuxt app sends; without it the endpoint returns HTTP 403.
        """
        order_match = re.search(r"/order/(\d+)", target.booking_url)
        if order_match is None:
            order_match = re.search(r"/api/order/(\d+)", target.booking_url)
        if order_match is None:
            return Result("error", detail="Cinema City booking URL has no presentation id")

        presentation_id = order_match.group(1)
        client = self._client(target)
        client.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://tickets.cinema-city.pl",
                "Referer": f"https://tickets.cinema-city.pl/order/{presentation_id}",
            }
        )
        client.headers.setdefault("uuid", str(uuid4()))

        presentation_response = client.get(
            f"https://tickets.cinema-city.pl/api/presentations/{presentation_id}"
        )
        presentation_response.raise_for_status()
        presentation_data = presentation_response.json()
        if error := presentation_data.get("error"):
            return Result(
                "closed",
                detail=f"Cinema City API error: {error.get('error') or error.get('message')}",
            )

        presentation = presentation_data["presentation"]
        if not presentation.get("isTicketingAllowedDuringSaleWindow", True):
            return Result("closed", detail="Cinema City says ticketing is not allowed")

        seatplan_response = client.post(
            "https://tickets.cinema-city.pl/api/seats/seatplanV2"
            f"?venueId={presentation['venueId']}&seatplanId={presentation['seatplanId']}",
            json={},
        )
        seatplan_response.raise_for_status()
        capacity = self._count_cinema_city_seats(seatplan_response.json())

        status_response = client.get(
            "https://tickets.cinema-city.pl/api/seats/seats-statusV2"
            f"?presentationId={presentation_id}"
            f"&venueTypeId={presentation['venueTypeId']}"
            f"&isReserved={1 if presentation.get('isReserved') else 0}"
        )
        if status_response.status_code in {403, 404, 409, 410}:
            return Result(
                "closed",
                detail=f"Cinema City seat status returned HTTP {status_response.status_code}",
            )
        status_response.raise_for_status()
        statuses = status_response.json().get("seats", {})
        if not statuses:
            return Result("closed", capacity=capacity, detail="Cinema City returned no seat statuses")

        # In observed responses, 0 means available; non-zero values are blocked,
        # selected, reserved, or otherwise unavailable to buy.
        available = sum(1 for value in statuses.values() if value == 0)
        return Result("open", available, max(capacity, len(statuses)), "Cinema City JSON seat status")

    def _probe_amondo(self, target: Target) -> Result:
        """Resolve Amondo's embedded Biletomat event and read its seat data.

        Amondo keeps the browser URL on ``kinoamondo.pl/repertuar/`` while the
        buy button opens a Biletomat/Kicket embedded flow.  The stable read-only
        endpoints are:

        * ``/marketplace/repertoire`` to map organizer/show to a concrete event
        * ``/api-ui/salesInfo`` for currently available numbered places
        * ``/api-ui/seats-plan`` for the room layout / total numbered places
        """
        parts = urlsplit(target.booking_url)
        query = dict(parse_qsl(parts.query))
        organizer_id = query.get("organizerId")
        show_id = query.get("showId")
        if not organizer_id or not show_id:
            return Result("error", detail="Amondo booking URL lacks organizerId/showId")

        client = self._client(target)
        repertoire_response = client.get(
            "https://api.biletomat.pl/marketplace/repertoire",
            params={
                "organizerId": organizer_id,
                "showId": show_id,
                "page": 0,
                "size": 100,
            },
        )
        repertoire_response.raise_for_status()
        repertoire = repertoire_response.json()
        events = self._extract_amondo_events(repertoire)
        if not events:
            return Result("closed", detail="Amondo repertoire returned no events")

        event = self._match_amondo_event(events, target.screening_start)
        if event is None:
            return Result("closed", detail="Amondo repertoire has no event matching target time")
        event_id = event["id"]

        sales_response = client.get(
            "https://biletomat.pl/api-ui/salesInfo",
            params={"events": event_id},
            headers={"Accept": "application/json"},
        )
        if sales_response.status_code in {404, 409, 410}:
            return Result("closed", detail=f"Amondo salesInfo returned HTTP {sales_response.status_code}")
        sales_response.raise_for_status()
        sales_items = sales_response.json()
        if not sales_items:
            return Result("closed", detail="Amondo salesInfo returned no event data")
        sale_info = sales_items[0].get("saleInfo") or {}
        availability = (sale_info.get("primarySale") or {}).get("availability") or {}
        if not availability.get("available", False):
            status = availability.get("status") or "not available"
            return Result("closed", detail=f"Amondo sale is not available: {status}")

        available_places = sale_info.get("primarySale", {}).get("availablePlaces") or []
        available = sum(
            int(place.get("remainingQuantity", 1) or 0)
            for place in available_places
            if place.get("placeType") == "NUMBERED"
        )

        seat_plan_response = client.get(
            f"https://biletomat.pl/api-ui/seats-plan/{event_id}",
            headers={"Accept": "application/json"},
        )
        seat_plan_response.raise_for_status()
        capacity = self._count_amondo_seats(seat_plan_response.json())
        if capacity == 0:
            capacity = len(available_places)

        return Result(
            "open",
            available,
            capacity,
            f"Amondo/Biletomat salesInfo + seats-plan event {event_id}",
        )

    @staticmethod
    def _extract_amondo_events(node: object) -> list[dict]:
        found: list[dict] = []

        def visit(value: object) -> None:
            if isinstance(value, dict):
                if "id" in value and (
                    "startsAt" in value
                    or "startDate" in value
                    or "displayPeriod" in value
                ):
                    found.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(node)
        return found

    @staticmethod
    def _match_amondo_event(events: list[dict], screening_start: datetime) -> Optional[dict]:
        def starts_at(event: dict) -> Optional[datetime]:
            value = (
                event.get("startsAt")
                or event.get("startDate")
                or ((event.get("displayPeriod") or {}).get("startsAt"))
            )
            if not value:
                return None
            try:
                return datetime.fromisoformat(str(value)).replace(tzinfo=None)
            except ValueError:
                return None

        candidates = [(event, starts_at(event)) for event in events]
        candidates = [(event, start) for event, start in candidates if start is not None]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: abs((item[1] - screening_start).total_seconds()),
        )[0]

    @staticmethod
    def _count_amondo_seats(seat_plan: object) -> int:
        if not isinstance(seat_plan, dict):
            return 0
        classic = seat_plan.get("classicSeatsPlanData") or {}
        schema_text = classic.get("schema")
        if not schema_text:
            return 0
        try:
            schema = json.loads(schema_text)
        except json.JSONDecodeError:
            return 0
        svg = unescape(str(schema.get("image") or ""))
        return len(re.findall(r'data-type=["\']place["\'][^>]*\bdata-place=', svg))

    @staticmethod
    def _count_cinema_city_seats(node: object) -> int:
        if isinstance(node, dict):
            is_seat = "tg" in node and "n" in node and not any(key in node for key in ("G", "R", "S"))
            return (1 if is_seat else 0) + sum(CutoffMonitor._count_cinema_city_seats(value) for value in node.values())
        if isinstance(node, list):
            return sum(CutoffMonitor._count_cinema_city_seats(value) for value in node)
        return 0

    def _probe_rendered(self, target: Target) -> Result:
        profile = (self.work_dir / f"chrome-{target.cinema_id}-{uuid4().hex}").resolve()
        output_path = (self.work_dir / f"latest-{target.cinema_id}.html").resolve()
        command = [
            str(self.chrome_path),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=12000",
            "--dump-dom",
            target.booking_url,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "no output"
            raise RuntimeError(f"headless browser returned {completed.returncode}: {detail}")
        output_path.write_text(completed.stdout, encoding="utf-8")
        return parse_rendered_seat_map(target.platform, completed.stdout)


def load_targets(path: Path) -> list[Target]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Target(
            cinema_id=item["cinema_id"],
            cinema=item["cinema"],
            platform=item["platform"],
            film=item["film"],
            screening_start=datetime.fromisoformat(item["screening_start_warsaw"]),
            booking_url=item["booking_url"],
            verify_ssl=item.get("verify_ssl", True),
            advertised_sale_time_to=item.get("advertised_sale_time_to", ""),
        )
        for item in raw
    ]


def append_row(path: Path, target: Target, checked_at: datetime, result: Result, duration_ms: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "checked_at_warsaw": checked_at.isoformat(timespec="seconds"),
                "cinema_id": target.cinema_id,
                "cinema": target.cinema,
                "platform": target.platform,
                "film": target.film,
                "screening_start_warsaw": target.screening_start.isoformat(timespec="seconds"),
                "minutes_from_start": round((checked_at.replace(tzinfo=None) - target.screening_start).total_seconds() / 60, 2),
                "state": result.state,
                "available": "" if result.available is None else result.available,
                "capacity": "" if result.capacity is None else result.capacity,
                "unavailable": "" if result.unavailable is None else result.unavailable,
                "advertised_sale_time_to": target.advertised_sale_time_to,
                "duration_ms": duration_ms,
                "detail": result.detail,
                "booking_url": target.booking_url,
            }
        )


async def run_monitor(targets: list[Target], output: Path, monitor: CutoffMonitor, interval: int, after_minutes: int) -> None:
    consecutive_closed = {target.cinema_id: 0 for target in targets}
    completed: set[str] = set()
    next_check = {
        target.cinema_id: max(datetime.now(), target.screening_start - timedelta(minutes=15))
        for target in targets
    }

    while len(completed) < len(targets):
        now = datetime.now()
        due = [
            target for target in targets
            if target.cinema_id not in completed and now >= next_check[target.cinema_id]
        ]
        if not due:
            await asyncio.sleep(min(10, max(1, min((moment - now).total_seconds() for key, moment in next_check.items() if key not in completed))))
            continue

        for target in due:
            checked_at = datetime.now().astimezone()
            started = time.monotonic()
            try:
                result = await asyncio.to_thread(monitor.probe, target)
            except Exception as exc:
                result = Result("error", detail=f"{type(exc).__name__}: {exc}")
            duration_ms = round((time.monotonic() - started) * 1000)
            append_row(output, target, checked_at, result, duration_ms)

            if result.state == "closed":
                consecutive_closed[target.cinema_id] += 1
            elif result.state == "open":
                consecutive_closed[target.cinema_id] = 0

            past_limit = datetime.now() >= target.screening_start + timedelta(minutes=after_minutes)
            if consecutive_closed[target.cinema_id] >= 3 or past_limit:
                completed.add(target.cinema_id)
            else:
                next_check[target.cinema_id] += timedelta(seconds=interval)
                while next_check[target.cinema_id] <= datetime.now():
                    next_check[target.cinema_id] += timedelta(seconds=interval)


async def run_once(targets: list[Target], output: Path, monitor: CutoffMonitor) -> None:
    for target in targets:
        checked_at = datetime.now().astimezone()
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(monitor.probe, target)
        except Exception as exc:
            result = Result("error", detail=f"{type(exc).__name__}: {exc}")
        duration_ms = round((time.monotonic() - started) * 1000)
        append_row(output, target, checked_at, result, duration_ms)


def main() -> None:
    parser = argparse.ArgumentParser(description="Observe when cinema seat maps close")
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--after-minutes", type=int, default=45)
    parser.add_argument("--once", action="store_true", help="Probe every target once and exit")
    parser.add_argument(
        "--chrome",
        type=Path,
        default=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    )
    args = parser.parse_args()
    work_dir = args.output.parent / ".monitor-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    monitor = CutoffMonitor(args.chrome, work_dir)
    try:
        targets = load_targets(args.targets)
        if args.once:
            asyncio.run(run_once(targets, args.output, monitor))
        else:
            asyncio.run(run_monitor(targets, args.output, monitor, args.interval, args.after_minutes))
    finally:
        monitor.close()


if __name__ == "__main__":
    main()
