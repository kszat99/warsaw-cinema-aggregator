import httpx
from datetime import date, datetime
from typing import List
from ..models import Screening
from .base import BaseAdapter
from ..normalize import normalize_title

class MultikinoAdapter(BaseAdapter):
    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        # self.cinema_id is the multikino ID string (e.g. "0040")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        
        main_url = f"{self.base_url}/teraz-gramy"
        try:
            # First get cookies from the main page if needed (shared client handles it)
            await client.get(main_url, headers=headers)
        except Exception:
            return []
            
        # 2. Query the showing groups API
        api_url = f"https://www.multikino.pl/api/microservice/showings/cinemas/{self.cinema_id}/films"
        
        # Multikino API expects datetime format 2026-02-22T00:00:00
        target_datetime_str = target_date.strftime("%Y-%m-%dT00:00:00")
        
        params = {
            "showingDate": target_datetime_str,
            "minEmbargoLevel": "3",
            "includesSession": "true",
            "includeSessionAttributes": "true"
        }
        
        try:
            resp = await client.get(api_url, params=params, headers=headers)
            
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []
            
        screenings = []
        if "result" not in data or not isinstance(data["result"], list):
            return screenings
            
        films = data["result"]
        
        for film in films:
            title_raw = film.get("filmTitle")
            if not title_raw:
                continue
                
            duration = film.get("runningTime")
            
            for group in film.get("showingGroups", []):
                for session in group.get("sessions", []):
                    starts_at_str = session.get("showTimeWithTimeZone") # e.g. 2026-02-23T10:30:00+01:00
                    if not starts_at_str:
                        continue
                    
                    try:
                        # Multikino returns ISO with offset like 2026-02-23T10:30:00+01:00
                        # Other adapters use naive datetimes, so strip tzinfo
                        starts_at = datetime.fromisoformat(starts_at_str).replace(tzinfo=None)
                    except ValueError:
                        continue
                        
                    booking_url = session.get("bookingUrl")
                    if booking_url and booking_url.startswith("/"):
                        booking_url = "https://www.multikino.pl" + booking_url
                        
                    # Extract attributes
                    lang = "org"
                    tags = []
                    
                    attributes = session.get("attributes", [])
                    for attr in attributes:
                        attr_name = (attr.get("name") or "").upper()
                        
                        if "DUBBING" in attr_name:
                            lang = "dub"
                        elif "NAPISY" in attr_name and not "UKR" in attr_name and not "UA" in attr_name:
                            lang = "nap"
                            
                        # Format tags
                        if "3D" in attr_name:
                            tags.append("3D")
                        elif "VIP" in attr_name:
                            tags.append("VIP")
                        elif "ATMOS" in attr_name:
                            tags.append("ATMOS")
                            
                    screenings.append(Screening(
                        cinema_id=self.cinema_id,
                        cinema_name=self.cinema_name,
                        title_raw=title_raw,
                        title_norm=normalize_title(title_raw),
                        starts_at=starts_at,
                        duration_min=duration,
                        language=lang,
                        tags=tags,
                        booking_url=booking_url,
                        poster_url=film.get("posterImageSrc")
                    ))
                    
        return screenings
