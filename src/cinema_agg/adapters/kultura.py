import re
from datetime import date, datetime
from typing import List
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseAdapter
from ..models import Screening
from ..normalize import normalize_title


class KulturaAdapter(BaseAdapter):
    """Read Kultura's public repertoire while its ticket host is unavailable."""

    _SCREENING_PATTERN = re.compile(
        r"rep_movie\(\s*'[^']*'\s*,\s*'(?P<movie_id>[^']+)'\s*,"
        r"\s*'(?P<hour>\d{1,2})'\s*,\s*'(?P<minute>\d{1,2})'\s*,"
        r"\s*'(?P<date>\d{4}-\d{2}-\d{2})'\s*,\s*'(?P<room>[^']*)'"
    )

    async def fetch_screenings(
        self, target_date: date, client: httpx.AsyncClient
    ) -> List[Screening]:
        endpoint = urljoin(
            self.base_url,
            "_core/_include/_rep/rep_posters.php",
        )
        response = await client.get(
            endpoint,
            params={
                "ajax": "1",
                "u_time": str(int(datetime.now().timestamp())),
                "rep_date": target_date.isoformat(),
            },
            headers={"Referer": urljoin(self.base_url, "repertuar/")},
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        screenings: List[Screening] = []
        seen = set()

        for item in soup.find_all(attrs={"onclick": re.compile(r"rep_movie\(")}):
            match = self._SCREENING_PATTERN.search(item.get("onclick", ""))
            image = item.find("img", alt=True)
            if not match or not image:
                continue

            screening_date = date.fromisoformat(match.group("date"))
            if screening_date != target_date:
                continue

            hour = int(match.group("hour"))
            minute = int(match.group("minute"))
            movie_id = match.group("movie_id")
            key = (movie_id, screening_date, hour, minute, match.group("room"))
            if key in seen:
                continue
            seen.add(key)

            title = image.get("alt", "").strip()
            if not title:
                continue

            room = "Rejs" if match.group("room") == "1" else "Kultura"
            booking_url = urljoin(
                self.base_url,
                f"repertuar/?date={target_date.isoformat()}",
            )
            poster_url = urljoin(self.base_url, image.get("src", "")) or None

            screenings.append(
                Screening(
                    cinema_id=self.cinema_id,
                    cinema_name=self.cinema_name,
                    title_raw=title,
                    title_norm=normalize_title(title),
                    starts_at=datetime(
                        target_date.year,
                        target_date.month,
                        target_date.day,
                        hour,
                        minute,
                    ),
                    tags=[room],
                    booking_url=booking_url,
                    poster_url=poster_url,
                )
            )

        return screenings
