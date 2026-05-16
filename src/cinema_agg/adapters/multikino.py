import os
import httpx
from datetime import date, datetime
from typing import List
from urllib.parse import quote
from ..models import Screening
from .base import BaseAdapter
from ..normalize import normalize_title

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
except ImportError:
    CurlAsyncSession = None

class MultikinoAdapter(BaseAdapter):
    _transport_logged = False
    _proxy_logged = False

    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        # self.cinema_id is the multikino ID string (e.g. "0040")
        if not MultikinoAdapter._transport_logged:
            transport = "curl_cffi chrome120" if CurlAsyncSession is not None else "httpx"
            print(f"  - Multikino transport: {transport}", flush=True)
            MultikinoAdapter._transport_logged = True

        proxy_template = os.getenv("MULTIKINO_PROXY_URL_TEMPLATE")
        if proxy_template and not MultikinoAdapter._proxy_logged:
            print("  - Multikino proxy: enabled via MULTIKINO_PROXY_URL_TEMPLATE", flush=True)
            MultikinoAdapter._proxy_logged = True
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{self.base_url}/teraz-gramy",
        }
        
        if CurlAsyncSession is None:
            main_url = f"{self.base_url}/teraz-gramy"
            try:
                # First get cookies from the main page if needed.
                await client.get(main_url, headers=headers)
            except Exception as e:
                print(f"  - Warning: Multikino preflight failed for {self.cinema_name}: {type(e).__name__}: {e}", flush=True)
            
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
            request_url, request_params = self._build_request_url(api_url, params)
            resp = await self._get(request_url, client, params=request_params, headers=headers)
            
            if resp.status_code != 200:
                body = resp.text[:200].replace("\n", " ").replace("\r", " ")
                reason = "Cloudflare challenge" if "Just a moment" in body else "HTTP error"
                print(
                    f"  - Warning: Multikino API returned {resp.status_code} ({reason}) for {self.cinema_name} "
                    f"on {target_date}: {body}",
                    flush=True,
                )
                return []
            data = resp.json()
        except Exception as e:
            print(f"  - Warning: Multikino API failed for {self.cinema_name} on {target_date}: {type(e).__name__}: {e}", flush=True)
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

    async def _get(self, url: str, client: httpx.AsyncClient, **kwargs):
        if CurlAsyncSession is None:
            return await client.get(url, **kwargs)

        async with CurlAsyncSession(impersonate="chrome120", timeout=30) as session:
            return await session.get(url, **kwargs)

    def _build_request_url(self, api_url: str, params: dict):
        proxy_template = os.getenv("MULTIKINO_PROXY_URL_TEMPLATE")
        if not proxy_template:
            return api_url, params

        target_url = str(httpx.URL(api_url, params=params))
        proxied_url = proxy_template.format(
            url=quote(target_url, safe=""),
            raw_url=target_url,
        )
        return proxied_url, None
