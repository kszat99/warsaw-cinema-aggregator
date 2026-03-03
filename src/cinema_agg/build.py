import asyncio
import json
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
from .models import BuildOutput, Screening
from .normalize import clean_title_for_search

import httpx
from typing import List, Optional

ADAPTER_MAP = {
    "novekino": NovekinoAdapter,
    "bilety24": Bilety24Adapter,
    "muranow": MuranowAdapter,
    "kinoteka": KinotekaAdapter,
    "cinema_city": CinemaCityAdapter,
    "multikino": MultikinoAdapter,
}

# Fix for Windows console encoding
# if sys.platform == "win32":
#     sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
#     sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

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
        
        search_title = clean_title_for_search(title_raw)
        print(f"  - Searching poster for: '{search_title}' (from '{title_raw}')")
        
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "api_key": self.api_key,
                    "query": search_title,
                    "include_adult": "false",
                    "page": 1,
                    "language": "pl-PL" # Try Polish first
                }
                r = await client.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
                r.raise_for_status()
                results = r.json().get("results", [])
                
                # If no results in Polish, try global search (English titles)
                if not results:
                    params.pop("language")
                    r = await client.get("https://api.themoviedb.org/3/search/movie", params=params, timeout=10)
                    r.raise_for_status()
                    results = r.json().get("results", [])

                if results:
                    p = results[0].get("poster_path")
                    if p:
                        url = f"https://image.tmdb.org/t/p/w185{p}"
                        self.cache[title_norm] = url
                        return url
        except Exception as e:
            print(f"Error fetching poster for {search_title}: {e}")
        
        # NOTE: We do NOT save 'None' to self.cache permanently anymore.
        # This ensures we retry missing posters on every build.
        return None

async def run_build():
    print("Starting Warsaw Cinema Aggregator build...", flush=True)
    
    # Range: Today + 13 days (total 14 days/2 weeks)
    today = date.today()
    date_range = [today + timedelta(days=i) for i in range(14)]
    
    all_screenings: List[Screening] = []
    
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for cinema_cfg in CINEMAS:
            adapter_cls = ADAPTER_MAP.get(cinema_cfg.adapter)
            if not adapter_cls:
                print(f"Warning: No adapter found for {cinema_cfg.id} ({cinema_cfg.adapter})")
                continue
                
            adapter = adapter_cls(cinema_cfg.id, cinema_cfg.name, cinema_cfg.url)
            print(f"Fetching screenings for {cinema_cfg.name} (14 days)...", flush=True)
            
            tasks = [adapter.fetch_screenings(target_date, client) for target_date in date_range]
            try:
                results = await asyncio.gather(*tasks)
                for screenings in results:
                    all_screenings.extend(screenings)
                print(f"  - Completed. Total screenings: {len(all_screenings)}", flush=True)
            except Exception as e:
                print(f"\n  - Error fetching {cinema_cfg.name}: {e}", flush=True)
                
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
    
    output = BuildOutput(
        generated_at=datetime.now(),
        screenings=unique_screenings
    )
    
    # Ensure dist directory exists
    dist_dir = Path("dist")
    dist_dir.mkdir(exist_ok=True)
    
    output_path = dist_dir / "showtimes.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json_data = output.model_dump_json(indent=2)
        f.write(json_data)
        
    print(f"Build complete! Saved {len(unique_screenings)} screenings to {output_path}")

if __name__ == "__main__":
    asyncio.run(run_build())
