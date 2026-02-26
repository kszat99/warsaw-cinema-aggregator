import asyncio
import httpx
import re
from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import List
from ..models import Screening
from .base import BaseAdapter
from ..normalize import normalize_title, extract_language_and_tags

class KinotekaAdapter(BaseAdapter):
    def __init__(self, cinema_id: str, cinema_name: str, base_url: str):
        super().__init__(cinema_id, cinema_name, base_url)
        self._runtime_cache = {}
        # Limit total concurrent detail requests to 5 to avoid blocking
        self._semaphore = asyncio.Semaphore(5)

    async def _fetch_details(self, client: httpx.AsyncClient, movie_url: str):
        if movie_url in self._runtime_cache:
            return self._runtime_cache[movie_url]
            
        async with self._semaphore:
            # Retry logic: 3 attempts with progressive delay
            for attempt in range(3):
                try:
                    movie_resp = await client.get(movie_url, follow_redirects=True, timeout=20.0)
                    if movie_resp.status_code == 200:
                        movie_soup = BeautifulSoup(movie_resp.text, "lxml")
                        
                        duration_min = None
                        dp_poster_url = None

                        # 1. Search for duration
                        duration_text = movie_soup.find(string=re.compile(r"czas trwania", re.I))
                        if duration_text:
                            look_in = duration_text.parent.get_text()
                            duration_match = re.search(r'(\d+)\s*min', look_in)
                            if duration_match:
                                duration_min = int(duration_match.group(1))
                        
                        # 2. Search for poster as fallback
                        poster_node = movie_soup.select_one(".e-movie__poster img") or movie_soup.select_one(".e-single-movie__poster img") or movie_soup.select_one("article img")
                        if poster_node:
                            dp_poster_url = poster_node.get("data-src") or poster_node.get("src")
                            if dp_poster_url and not dp_poster_url.startswith('http'):
                                from urllib.parse import urljoin
                                dp_poster_url = urljoin(self.base_url, dp_poster_url)
                        
                        data = {
                            'duration': duration_min,
                            'poster': dp_poster_url
                        }
                        self._runtime_cache[movie_url] = data
                        return data
                    elif movie_resp.status_code == 429:
                        await asyncio.sleep(2 * (attempt + 1))
                    else:
                        break # Other status codes, don't retry immediately
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(1 * (attempt + 1))
                    else:
                        print(f"      - Warning: Failed to fetch data from {movie_url} after 3 attempts: {e}")
        return None

    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        url = f"{self.base_url}?date={target_date.isoformat()}"
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        screenings = []
        
        movie_articles = soup.select("article.e-movie")
        
        # Prepare list of movie detail tasks
        detail_tasks = []
        movie_data_map = {} # movie_url -> article
        
        for article in movie_articles:
            title_node = article.select_one(".e-movie__heading-link")
            if not title_node:
                continue
            movie_url = title_node.get("href")
            if movie_url:
                if not movie_url.startswith('http'):
                    from urllib.parse import urljoin
                    movie_url = urljoin(self.base_url, movie_url)
                detail_tasks.append(self._fetch_details(client, movie_url))
                movie_data_map[movie_url] = article

        # Fetch all details in parallel
        await asyncio.gather(*detail_tasks)

        for movie_url, article in movie_data_map.items():
            title_node = article.select_one(".e-movie__heading-link")
            title_raw = title_node.get_text(strip=True)
            
            cache_data = self._runtime_cache.get(movie_url, {})
            duration_min = cache_data.get('duration')
            dp_poster_url = cache_data.get('poster')

            showtime_links = article.select(".e-movie__screenings li a")
            for link in showtime_links:
                hour_str = link.get("data-hour")
                day_str = link.get("data-day")
                booking_url = link.get("href")
                
                if not hour_str or not day_str:
                    continue
                    
                try:
                    starts_at = datetime.strptime(f"{day_str} {hour_str}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                
                if starts_at.date() != target_date:
                    continue

                lang, tags = extract_language_and_tags(title_raw)

                # Extract poster URL
                poster_url = None
                img_node = article.select_one(".e-movie__poster img")
                if img_node:
                    poster_url = img_node.get("data-src") or img_node.get("src")
                    if poster_url and not poster_url.startswith('http'):
                        from urllib.parse import urljoin
                        poster_url = urljoin(self.base_url, poster_url)
                
                if not poster_url:
                    poster_url = dp_poster_url

                screenings.append(Screening(
                    cinema_id=self.cinema_id,
                    cinema_name=self.cinema_name,
                    title_raw=title_raw,
                    title_norm=normalize_title(title_raw),
                    starts_at=starts_at,
                    duration_min=duration_min,
                    language=lang,
                    tags=tags,
                    booking_url=booking_url,
                    poster_url=poster_url
                ))
                
        return screenings
