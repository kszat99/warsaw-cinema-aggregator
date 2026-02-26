import httpx
from datetime import date, datetime
from typing import List
from ..models import Screening
from .base import BaseAdapter
from ..normalize import normalize_title

class CinemaCityAdapter(BaseAdapter):
    async def fetch_screenings(self, target_date: date) -> List[Screening]:
        # self.cinema_id is the numeric ID (e.g. 1088)
        url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{self.cinema_id}/at-date/{target_date.isoformat()}?attr=&lang=pl_PL"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Referer': 'https://www.cinema-city.pl/'
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                return []

        films_data = {f['id']: f for f in data.get('body', {}).get('films', [])}
        events = data.get('body', {}).get('events', [])
        
        screenings = []
        for event in events:
            film_id = event.get('filmId')
            film = films_data.get(film_id)
            if not film:
                continue
                
            title_raw = film.get('name')
            # datetime.fromisoformat handles "2026-02-18T15:20:00"
            try:
                starts_at = datetime.fromisoformat(event.get('eventDateTime'))
            except ValueError:
                continue
                
            booking_url = event.get('bookingLink')
            
            # Extract language/tags from attributes
            attr_ids = set(event.get('attributeIds', []) + film.get('attributeIds', []))
            lang = "org"
            tags = []
            
            if "subbed" in attr_ids or "first-subbed-lang-pl" in attr_ids:
                lang = "nap"
            elif "dubbed" in attr_ids or "dubbed-lang-pl" in attr_ids:
                lang = "dub"
            
            if "3d" in attr_ids:
                tags.append("3D")
            if "imax" in attr_ids or "laser-barco" in attr_ids:
                tags.append("IMAX")
            if "4dx" in attr_ids:
                tags.append("4DX")

            # Special case for Sadyba: Only include IMAX screenings
            if self.cinema_id == "1089" and "IMAX" not in tags:
                continue

            screenings.append(Screening(
                cinema_id=self.cinema_id,
                cinema_name=f"{self.cinema_name} (only IMAX)" if self.cinema_id == "1089" else self.cinema_name,
                title_raw=title_raw,
                title_norm=normalize_title(title_raw),
                starts_at=starts_at,
                duration_min=film.get('length'),
                language=lang,
                tags=tags,
                booking_url=booking_url,
                poster_url=film.get('posterLink')
            ))
            
        return screenings
