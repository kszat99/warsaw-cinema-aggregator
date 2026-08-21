import httpx
from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import List
import re

from .base import BaseAdapter
from ..models import Screening
from ..normalize import normalize_title, extract_language_and_tags

class NovekinoAdapter(BaseAdapter):
    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        # URL format: ?sort=Date&date=YYYY-MM-DD&datestart=0
        url = f"{self.base_url}?sort=Date&date={target_date.isoformat()}&datestart=0"
        
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
            
        soup = BeautifulSoup(response.text, 'lxml')
        screenings = []
        
        # In Novekino multiplexes, movies are in <div class="movies-movie">
        items = soup.find_all('div', class_='movies-movie')
        
        for item in items:
            title_node = item.find(['h2', 'h3'], class_='movies-movie__single__title')
            if not title_node:
                continue
            
            title_raw = title_node.text.strip()
            
            # Duration and Version are in <ul class="movies-movie__single__moreinfo">
            info_node = item.find('ul', class_='movies-movie__single__moreinfo')
            duration_min = None
            format_raw = ""
            if info_node:
                text = info_node.text.strip()
                # Version: DUB / ORYG / NAP
                match_dur = re.search(r'(\d+)\s*min', text)
                if match_dur:
                    duration_min = int(match_dur.group(1))
                
                # Check for explicit version list item
                version_li = info_node.find('li', string=re.compile(r'wersja:'))
                if version_li:
                    format_raw = version_li.text.replace('wersja:', '').strip()
            
            # Times are in <ul class="movies-movie__single__options__hours">
            # MSI 1.8.72.2 renamed showtime links from js-repo-popup to
            # js-link-popup. Keep both selectors because the same adapter is
            # also used by Novekino sites that may still serve the old markup.
            hour_links = item.select('a.js-repo-popup, a.js-link-popup')
            seen_showtimes = set()
            
            for hl in hour_links:
                time_str = hl.text.strip()
                # MSI renders separate desktop/mobile controls for the same
                # event. Do not emit the duplicated screening.
                showtime_key = (time_str, hl.get('data-event'), hl.get('href'))
                if showtime_key in seen_showtimes:
                    continue
                seen_showtimes.add(showtime_key)

                # Example time: "18:00"
                try:
                    hour, minute = map(int, time_str.split(':'))
                    starts_at = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
                except ValueError:
                    continue
                
                language, tags = extract_language_and_tags(title_raw, format_raw)
                
                # Booking URL is relative
                booking_url = hl.get('href')
                if booking_url and booking_url.startswith('/'):
                    from urllib.parse import urljoin
                    booking_url = urljoin(self.base_url, booking_url)
                
                # The user noted that Default.aspx with typetran=1 (reservation) often fails.
                # OrderTickets.aspx with typetran=0 (purchase) is more reliable.
                if booking_url:
                    booking_url = booking_url.replace('Default.aspx', 'OrderTickets.aspx')
                    booking_url = booking_url.replace('typetran=1', 'typetran=0')

                # Extract poster URL
                poster_url = None
                img_node = (
                    item.find('div', class_='movies-movie__single__img')
                    or item.find('div', class_='movies-movie__single__poster')
                )
                if img_node:
                    img_node = img_node.find('img')
                if img_node:
                    poster_url = img_node.get('src')
                    if poster_url and not poster_url.startswith('http'):
                        from urllib.parse import urljoin
                        poster_url = urljoin(self.base_url, poster_url)

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
