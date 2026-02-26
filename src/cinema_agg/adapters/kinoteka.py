import httpx
import re
from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import List
from ..models import Screening
from .base import BaseAdapter
from ..normalize import normalize_title, extract_language_and_tags

class KinotekaAdapter(BaseAdapter):
    async def fetch_screenings(self, target_date: date) -> List[Screening]:
        url = f"{self.base_url}?date={target_date.isoformat()}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")
            screenings = []
            
            movie_articles = soup.select("article.e-movie")
            
            # Simple cache for runtimes to avoid multiple requests for the same movie
            # You can also use a class-level cache to persist across multiple target_dates
            if not hasattr(self, '_runtime_cache'):
                self._runtime_cache = {}

            for article in movie_articles:
                title_node = article.select_one(".e-movie__heading-link")
                if not title_node:
                    continue
                title_raw = title_node.get_text(strip=True)
                movie_url = title_node.get("href")
                
                # Fetch runtime and poster if not in cache
                duration_min = None
                dp_poster_url = None
                if movie_url:
                    if movie_url in self._runtime_cache:
                        cache_data = self._runtime_cache[movie_url]
                        duration_min = cache_data.get('duration')
                        dp_poster_url = cache_data.get('poster')
                    else:
                        try:
                            # Reuse the client for movie detail pages
                            movie_resp = await client.get(movie_url, follow_redirects=True)
                            if movie_resp.status_code == 200:
                                movie_soup = BeautifulSoup(movie_resp.text, "lxml")
                                
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
                                
                                self._runtime_cache[movie_url] = {
                                    'duration': duration_min,
                                    'poster': dp_poster_url
                                }
                        except Exception as e:
                            print(f"      - Warning: Failed to fetch data from {movie_url}: {e}")

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
                        # Try data-src first (lazy loading), then fallback to src
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
