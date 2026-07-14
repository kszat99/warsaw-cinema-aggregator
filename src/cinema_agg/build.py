import asyncio
import json
import os
import sys
import io
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import List

from .config import CINEMAS, TMDB_API_KEY
from .adapters.novekino import NovekinoAdapter
from .adapters.bilety24 import Bilety24Adapter
from .adapters.muranow import MuranowAdapter
from .adapters.kinoteka import KinotekaAdapter
from .adapters.cinema_city import CinemaCityAdapter
from .adapters.multikino import MultikinoAdapter
from .adapters.helios import HeliosAdapter
from .adapters.iluzjon import IluzjonAdapter
from .adapters.amondo import AmondoAdapter
from .adapters.ujazdowski import UjazdowskiAdapter
from .models import BuildOutput, Screening
from .normalize import clean_title_for_search, clean_title_search_candidates

import httpx
from typing import List, Optional

MULTIKINO_REQUEST_DELAY_SECONDS = int(os.getenv("MULTIKINO_REQUEST_DELAY_SECONDS", "45"))
MULTIKINO_RETRY_DELAYS_SECONDS = [
    int(delay)
    for delay in os.getenv("MULTIKINO_RETRY_DELAYS_SECONDS", "120,300").split(",")
    if delay.strip() and int(delay) > 0
]

ADAPTER_MAP = {
    "novekino": NovekinoAdapter,
    "bilety24": Bilety24Adapter,
    "muranow": MuranowAdapter,
    "kinoteka": KinotekaAdapter,
    "cinema_city": CinemaCityAdapter,
    "multikino": MultikinoAdapter,
    "helios": HeliosAdapter,
    "iluzjon": IluzjonAdapter,
    "amondo": AmondoAdapter,
    "ujazdowski": UjazdowskiAdapter,
}

# Fix for Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class PosterService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cache_path = Path("dist/poster_cache.json")
        self.cache = {}
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
            except:
                pass

    def save_cache(self):
        self.cache_path.parent.mkdir(exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    async def get_poster(self, title_norm: str, title_raw: str) -> Optional[str]:
        if title_norm in self.cache:
            return self.cache[title_norm]
        
        search_titles = clean_title_search_candidates(title_raw) or [clean_title_for_search(title_raw)]
        print(f"  - Searching poster for: '{search_titles[0]}' (from '{title_raw}')")
        
        try:
            async with httpx.AsyncClient() as client:
                for search_title in search_titles:
                    for language in ("pl-PL", None):
                        params = {
                            "api_key": self.api_key,
                            "query": search_title,
                            "include_adult": "false",
                            "page": 1,
                        }
                        if language:
                            params["language"] = language

                        r = await client.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
                        r.raise_for_status()
                        results = r.json().get("results", [])

                        for result in results[:3]:
                            p = result.get("poster_path")
                            if p:
                                url = f"https://image.tmdb.org/t/p/w185{p}"
                                self.cache[title_norm] = url
                                if search_title != search_titles[0]:
                                    print(f"    - Poster found with fallback search: '{search_title}'")
                                return url
        except Exception as e:
            print(f"Error fetching poster for {search_titles[0]}: {e}")
        
        # NOTE: We do NOT save 'None' to self.cache permanently anymore.
        # This ensures we retry missing posters on every build.
        return None


def update_cinema_health(cinema_screening_counts: dict, generated_at: datetime) -> dict:
    health_path = Path("dist/cinema_health.json")
    previous = {}
    if health_path.exists():
        try:
            with open(health_path, "r", encoding="utf-8") as f:
                previous = json.load(f)
        except Exception:
            previous = {}

    previous_cinemas = previous.get("cinemas", {})
    previous_adapters = previous.get("adapters", {})
    cinemas = {}
    adapters = {}
    alerts = []

    for cinema in CINEMAS:
        count = int(cinema_screening_counts.get(cinema.id, 0))
        previous_streak = int(previous_cinemas.get(cinema.id, {}).get("zero_streak", 0) or 0)
        zero_streak = previous_streak + 1 if count == 0 else 0
        cinemas[cinema.id] = {
            "name": cinema.name,
            "adapter": cinema.adapter,
            "screenings": count,
            "zero_streak": zero_streak,
        }
        if zero_streak >= 3:
            alerts.append({
                "scope": "cinema",
                "id": cinema.id,
                "name": cinema.name,
                "adapter": cinema.adapter,
                "zero_streak": zero_streak,
            })

    for adapter in sorted({cinema.adapter for cinema in CINEMAS}):
        adapter_cinemas = [cinema for cinema in CINEMAS if cinema.adapter == adapter]
        count = sum(int(cinema_screening_counts.get(cinema.id, 0)) for cinema in adapter_cinemas)
        previous_streak = int(previous_adapters.get(adapter, {}).get("zero_streak", 0) or 0)
        zero_streak = previous_streak + 1 if count == 0 else 0
        adapters[adapter] = {
            "screenings": count,
            "cinemas": [cinema.id for cinema in adapter_cinemas],
            "zero_streak": zero_streak,
        }
        if zero_streak >= 3:
            alerts.append({
                "scope": "adapter",
                "id": adapter,
                "name": adapter,
                "zero_streak": zero_streak,
            })

    health = {
        "generated_at": generated_at.isoformat(),
        "threshold_days": 3,
        "alerts": alerts,
        "cinemas": cinemas,
        "adapters": adapters,
    }

    health_path.parent.mkdir(exist_ok=True)
    with open(health_path, "w", encoding="utf-8") as f:
        json.dump(health, f, indent=2, ensure_ascii=False)

    if alerts:
        print(f"Health check warnings: {len(alerts)} zero-screening streaks reached threshold.", flush=True)

    return health

async def fetch_screenings_for_cinema(adapter, cinema_cfg, date_range, client) -> List[Screening]:
    if cinema_cfg.adapter != "multikino":
        tasks = [adapter.fetch_screenings(target_date, client) for target_date in date_range]
        results = await asyncio.gather(*tasks)
        return [screening for screenings in results for screening in screenings]

    screenings: List[Screening] = []
    for index, target_date in enumerate(date_range):
        if index > 0:
            print(
                f"  - Multikino slow mode: waiting {MULTIKINO_REQUEST_DELAY_SECONDS}s before {target_date}",
                flush=True,
            )
            await asyncio.sleep(MULTIKINO_REQUEST_DELAY_SECONDS)

        day_screenings = []
        for attempt, retry_delay in enumerate([0] + MULTIKINO_RETRY_DELAYS_SECONDS, start=1):
            if retry_delay:
                print(
                    f"  - Multikino slow mode: retrying {target_date} in {retry_delay}s "
                    f"(attempt {attempt})",
                    flush=True,
                )
                await asyncio.sleep(retry_delay)

            day_screenings = await adapter.fetch_screenings(target_date, client)
            if day_screenings:
                break

        print(
            f"  - Multikino slow mode: {target_date} returned {len(day_screenings)} screenings",
            flush=True,
        )
        screenings.extend(day_screenings)

    return screenings

def apply_title_canonicalization(screenings: List[Screening]) -> None:
    title_norms = sorted({s.title_norm for s in screenings if s.title_norm}, key=len, reverse=True)
    canonical_by_norm = {}

    for short_title in sorted(title_norms, key=len):
        if len(short_title) < 16:
            continue

        for long_title in title_norms:
            if len(long_title) <= len(short_title):
                continue
            if not long_title.startswith(short_title):
                continue

            # Only merge apparent mid-word truncation, e.g. "... ale ko" -> "... ale kosmos".
            # Avoid merging real sequel/title variants like "mortal kombat" -> "mortal kombat 2".
            next_char = long_title[len(short_title)]
            if next_char != " ":
                canonical_by_norm[short_title] = long_title
                break

    if canonical_by_norm:
        print(f"Canonicalized {len(canonical_by_norm)} truncated title variants.", flush=True)

    for screening in screenings:
        screening.title_norm = canonical_by_norm.get(screening.title_norm, screening.title_norm)

async def run_build():
    print("Starting Warsaw Cinema Aggregator build...", flush=True)
    
    # Range: Today + 13 days (total 14 days/2 weeks)
    today = date.today()
    date_range = [today + timedelta(days=i) for i in range(14)]
    
    all_screenings: List[Screening] = []
    cinema_screening_counts = {}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for cinema_cfg in CINEMAS:
            adapter_cls = ADAPTER_MAP.get(cinema_cfg.adapter)
            if not adapter_cls:
                print(f"Warning: No adapter found for {cinema_cfg.id} ({cinema_cfg.adapter})")
                continue
                
            adapter = adapter_cls(cinema_cfg.id, cinema_cfg.name, cinema_cfg.url)
            print(f"Fetching screenings for {cinema_cfg.name} (14 days)...", flush=True)
            
            try:
                screenings = await fetch_screenings_for_cinema(adapter, cinema_cfg, date_range, client)
                cinema_total = len(screenings)
                all_screenings.extend(screenings)
                cinema_screening_counts[cinema_cfg.id] = cinema_total
                print(f"  - Completed. Cinema screenings: {cinema_total}. Total screenings: {len(all_screenings)}", flush=True)
            except Exception as e:
                print(f"\n  - Error fetching {cinema_cfg.name}: {e}", flush=True)

    multikino_configs = [c for c in CINEMAS if c.adapter == "multikino"]
    multikino_total = sum(cinema_screening_counts.get(c.id, 0) for c in multikino_configs)
    if multikino_configs and multikino_total == 0:
        raise RuntimeError(
            "Multikino returned 0 screenings across all configured cinemas. "
            "Refusing to publish a partial build; check the Multikino warnings above."
        )

    apply_title_canonicalization(all_screenings)
                
    # Deduplicate: (starts_at, title_norm, cinema_id)
    seen = set()
    unique_screenings = []
    for s in all_screenings:
        key = (s.starts_at, s.title_norm, s.cinema_id)
        if key not in seen:
            seen.add(key)
            unique_screenings.append(s)
            
    # Enrich with posters
    poster_service = PosterService(TMDB_API_KEY)
    
    # Find unique movies to fetch posters for
    unique_movies = {}
    fallback_posters = {} # title_norm -> first available poster_url from adapters
    
    for s in unique_screenings:
        if s.title_norm not in unique_movies:
            unique_movies[s.title_norm] = s.title_raw
        if s.poster_url and s.title_norm not in fallback_posters:
            fallback_posters[s.title_norm] = s.poster_url
            
    print(f"Fetching posters for {len(unique_movies)} unique movies...")
    movie_posters = {}
    for title_norm, title_raw in unique_movies.items():
        poster_url = await poster_service.get_poster(title_norm, title_raw)
        
        # Fallback to adapter-provided poster if TMDB failed
        if not poster_url and title_norm in fallback_posters:
            poster_url = fallback_posters[title_norm]
            
        movie_posters[title_norm] = poster_url
        
    for s in unique_screenings:
        s.poster_url = movie_posters.get(s.title_norm)
        
    poster_service.save_cache()

    # Sort by time
    unique_screenings.sort(key=lambda s: s.starts_at)
    
    generated_at = datetime.now()
    output = BuildOutput(
        generated_at=generated_at,
        screenings=unique_screenings
    )
    
    # Ensure dist directory exists
    dist_dir = Path("dist")
    dist_dir.mkdir(exist_ok=True)
    
    output_path = dist_dir / "showtimes.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json_data = output.model_dump_json(indent=2)
        f.write(json_data)

    health = update_cinema_health(cinema_screening_counts, generated_at)
        
    print(f"Build complete! Saved {len(unique_screenings)} screenings to {output_path}")
    if health["alerts"]:
        print("Health alerts will be reported by the deploy workflow if committed.", flush=True)

if __name__ == "__main__":
    asyncio.run(run_build())
