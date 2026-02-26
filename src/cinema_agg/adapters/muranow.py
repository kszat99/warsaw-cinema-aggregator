import httpx
from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import List
import re

from ..adapters.base import BaseAdapter
from ..models import Screening
from ..normalize import normalize_title, extract_language_and_tags

class MuranowAdapter(BaseAdapter):
    def __init__(self, cinema_id: str, cinema_name: str, base_url: str):
        super().__init__(cinema_id, cinema_name, base_url)
        self._movie_cache = {} # URL -> {duration_min, language, tags}

    async def _fetch_movie_details(self, movie_url: str):
        """Fetch and parse movie detail page for duration and language."""
        if movie_url in self._movie_cache:
            return self._movie_cache[movie_url]
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(movie_url, timeout=20.0)
                resp.raise_for_status()
            
            detail_soup = BeautifulSoup(resp.text, 'lxml')
            
            duration_min = None
            language = "org"
            tags = []
            poster_url = None
            
            # Look for main image
            # Commonly Muranów has a main image in div with class 'c-article__image' or similar
            img_node = detail_soup.find('img', class_='c-image--main')
            if not img_node:
                img_node = detail_soup.find('div', class_='c-article__image')
                if img_node:
                    img_node = img_node.find('img')
            
            if img_node:
                poster_url = img_node.get('src')
                if poster_url and not poster_url.startswith('http'):
                    from urllib.parse import urljoin
                    poster_url = urljoin(movie_url, poster_url)

            # Look for "Czas trwania" and "Język"
            info_text = detail_soup.get_text()
            
            dur_match = re.search(r'Czas trwania\s+(\d+)\s*min', info_text, re.IGNORECASE)
            if dur_match:
                duration_min = int(dur_match.group(1))
                
            lang_match = re.search(r'Język\s+([^|\n\r]+)', info_text, re.IGNORECASE)
            if lang_match:
                lang_val = lang_match.group(1).lower().strip()
                if "napisy" in lang_val:
                    language = "nap"
                elif "dub" in lang_val:
                    language = "dub"
                elif "lektor" in lang_val:
                    language = "voiceover"

            details = {
                "duration_min": duration_min,
                "language": language,
                "tags": tags,
                "poster_url": poster_url
            }
            self._movie_cache[movie_url] = details
            return details
        except Exception as e:
            print(f"Warning: Failed to fetch movie details from {movie_url}: {e}")
            return None

    async def fetch_screenings(self, target_date: date) -> List[Screening]:
        async with httpx.AsyncClient() as client:
            response = await client.get(self.base_url, timeout=30.0)
            response.raise_for_status()
            
        soup = BeautifulSoup(response.text, 'lxml')
        screenings = []
        
        days = soup.find_all('div', class_='calendar-seance-full__day')
        
        for day_node in days:
            day_num_node = day_node.find('span', class_='cell-date-header__day-num')
            if not day_num_node or day_num_node.text.strip() != str(target_date.day):
                continue
            
            movie_items = day_node.find_all('div', class_='movie-calendar-info')
            
            for m_item in movie_items:
                title_node = m_item.find('h5', class_='movie-calendar-info__title')
                time_node = m_item.find('span', class_='movie-calendar-info__date')
                
                if not title_node or not time_node:
                    continue
                
                title_raw = title_node.text.strip()
                time_str = time_node.text.strip()
                
                try:
                    hour, minute = map(int, time_str.split(':'))
                    starts_at = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
                except ValueError:
                    continue
                
                # Muranów expand link has movie description link
                movie_link_node = m_item.find('a', class_='c-button-tickets--movie-link')
                movie_url = movie_link_node.get('href') if movie_link_node else None
                
                duration_min = None
                language, tags = extract_language_and_tags(title_raw)
                poster_url = None
                
                if movie_url:
                    if not movie_url.startswith('http'):
                        from urllib.parse import urljoin
                        movie_url = urljoin("https://kinomuranow.pl", movie_url)
                    
                    details = await self._fetch_movie_details(movie_url)
                    if details:
                        duration_min = details['duration_min']
                        if details['language'] != "org":
                            language = details['language']
                        tags.extend([t for t in details['tags'] if t not in tags])
                        poster_url = details.get('poster_url')

                inner = m_item.find('div', class_='movie-calendar-info__inner')
                booking_url = None
                if inner and inner.get('data-id'):
                    seance_id = inner.get('data-id')
                    booking_url = f"https://kinomuranow.pl/tickets/{seance_id}/buy"

                screenings.append(Screening(
                    cinema_id=self.cinema_id,
                    cinema_name=self.cinema_name,
                    title_raw=title_raw,
                    title_norm=normalize_title(title_raw),
                    starts_at=starts_at,
                    duration_min=duration_min,
                    language=language,
                    tags=tags,
                    booking_url=booking_url,
                    poster_url=poster_url
                ))
            
        return screenings
