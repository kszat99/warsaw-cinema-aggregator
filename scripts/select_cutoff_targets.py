import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup


TRACKABLE_PLATFORMS = {
    "wisla": "msi",
    "atlantic": "msi",
    "kultura": "msi",
    "kinoteka": "kinoteka",
    "1074": "cinema_city",
    "1061": "cinema_city",
    "1060": "cinema_city",
    "1070": "cinema_city",
    "1068": "cinema_city",
    "1096": "cinema_city",
    "1069": "cinema_city",
    "0040": "multikino",
    "0013": "multikino",
    "0052": "multikino",
    "0024": "multikino",
    "0025": "multikino",
    "57": "helios",
    "elektronik": "bilety24",
    "amondo": "amondo",
}

CINEMA_CITY_IDS = {"1074", "1061", "1060", "1070", "1068", "1096", "1069"}
MULTIKINO_IDS = {"0040", "0013", "0052", "0024", "0025"}


@dataclass
class Selection:
    cinema_id: str
    cinema: str
    platform: str
    film: str
    screening_start_warsaw: str
    booking_url: str
    verify_ssl: bool = True

    def as_dict(self) -> dict:
        data = {
            "cinema_id": self.cinema_id,
            "cinema": self.cinema,
            "platform": self.platform,
            "film": self.film,
            "screening_start_warsaw": self.screening_start_warsaw,
            "booking_url": self.booking_url,
        }
        if not self.verify_ssl:
            data["verify_ssl"] = False
        return data


def load_showtimes(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["screenings"]


def target_sort_key(screening: dict) -> datetime:
    return datetime.fromisoformat(screening["starts_at"])


def normalized_platform_id(cinema_id: str, platform: str) -> str:
    if cinema_id in CINEMA_CITY_IDS:
        return f"cinema_city_{cinema_id}"
    if cinema_id in MULTIKINO_IDS:
        return f"multikino_{cinema_id}"
    if cinema_id == "57":
        return "helios_57"
    return cinema_id


def repertoire_url_for_msi(booking_url: str, target_date: date) -> str:
    parts = urlsplit(booking_url)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            "/MSI/mvc/pl",
            urlencode({"sort": "Date", "date": target_date.isoformat(), "datestart": "0"}),
            "",
        )
    )


def resolve_kultura_booking_url(target_date: date, earliest: datetime) -> Selection | None:
    url = f"https://rezerwacja.kinokultura.pl/MSI/mvc/pl?sort=Date&date={target_date.isoformat()}&datestart=0"
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True, verify=False, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(response.text, "lxml")
    candidates = []
    for link in soup.select('a[href*="event_id="]'):
        text = link.get_text(" ", strip=True)
        match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
        if not match:
            parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""
            match = re.search(r"\b(\d{1,2}):(\d{2})\b", parent_text)
        if not match:
            continue
        starts_at = datetime.combine(target_date, time(int(match.group(1)), int(match.group(2))))
        if starts_at < earliest:
            continue
        href = str(link.get("href", ""))
        event_id = dict(parse_qsl(urlsplit(href).query)).get("event_id")
        if not event_id:
            data_event = link.get("data-event")
            event_id = str(data_event) if data_event else ""
        if not event_id:
            continue
        candidates.append((starts_at, event_id, text or "Kino Kultura"))

    if not candidates:
        return None

    starts_at, event_id, title = sorted(candidates, key=lambda item: item[0])[0]
    booking_url = (
        "https://rezerwacja.kinokultura.pl/MSI/Default.aspx?"
        + urlencode(
            {
                "event_id": event_id,
                "typetran": "0",
                "returnlink": f"~/mvc/pl?sort=Date&date={target_date.isoformat()}",
            }
        )
    )
    return Selection(
        cinema_id="kultura",
        cinema="Kino Kultura",
        platform="msi",
        film=title,
        screening_start_warsaw=starts_at.isoformat(timespec="seconds"),
        booking_url=booking_url,
        verify_ssl=False,
    )


def select_targets(showtimes: list[dict], target_date: date, earliest_time: time) -> list[Selection]:
    earliest = datetime.combine(target_date, earliest_time)
    selected: list[Selection] = []
    by_cinema: dict[str, list[dict]] = {}

    for screening in showtimes:
        cinema_id = screening["cinema_id"]
        if cinema_id not in TRACKABLE_PLATFORMS or not screening.get("booking_url"):
            continue
        starts_at = datetime.fromisoformat(screening["starts_at"])
        if starts_at.date() != target_date or starts_at < earliest:
            continue
        if cinema_id == "elektronik" and "mała sala" in (screening.get("title_raw") or "").lower():
            continue
        by_cinema.setdefault(cinema_id, []).append(screening)

    for cinema_id, screenings in sorted(by_cinema.items()):
        if cinema_id == "kultura":
            continue
        screening = sorted(screenings, key=target_sort_key)[0]
        platform = TRACKABLE_PLATFORMS[cinema_id]
        selected.append(
            Selection(
                cinema_id=normalized_platform_id(cinema_id, platform),
                cinema=screening.get("cinema_name") or cinema_id,
                platform=platform,
                film=screening.get("title_raw") or "",
                screening_start_warsaw=screening["starts_at"],
                booking_url=screening["booking_url"],
            )
        )

    kultura = resolve_kultura_booking_url(target_date, earliest)
    if kultura:
        selected.append(kultura)

    selected.sort(key=lambda item: (item.screening_start_warsaw, item.cinema))
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Select tomorrow cutoff-monitor targets from showtimes")
    parser.add_argument("--showtimes", type=Path, default=Path("dist/showtimes.json"))
    parser.add_argument("--date", required=True, help="Target date, YYYY-MM-DD")
    parser.add_argument("--earliest-start", default="11:00", help="Earliest screening start, HH:MM")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date)
    hour, minute = (int(part) for part in args.earliest_start.split(":", 1))
    targets = select_targets(load_showtimes(args.showtimes), target_date, time(hour, minute))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps([target.as_dict() for target in targets], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Selected {len(targets)} cutoff targets for {target_date.isoformat()} at {args.output}")


if __name__ == "__main__":
    main()
