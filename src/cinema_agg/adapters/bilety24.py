import httpx
from bs4 import BeautifulSoup
from datetime import date, datetime
from typing import List
import re

from ..adapters.base import BaseAdapter
from ..models import Screening
from ..normalize import normalize_title, extract_language_and_tags

class Bilety24Adapter(BaseAdapter):
    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        # URL format: ?b24_day=YYYY-MM-DD
        url = f"{self.base_url.rstrip('/')}/?b24_day={target_date.isoformat()}"
        
        response = await client.get(url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
            
        soup = BeautifulSoup(response.text, 'lxml')
        screenings = []
        
        # Screenings are usually in <div class="list-item">
        items = soup.find_all('div', class_='list-item')
        
        if not items:
            # Check if there is some "no screenings" message or if we were blocked
            if "Przekroczono limit zapytań" in response.text or "403 Forbidden" in response.text:
                print(f"  Warning: Possible block/limit on {self.cinema_name} for {target_date}")
            return []
            
        for item in items:
            title_link = item.find('a', class_='b24-link text')
            if not title_link:
                title_node = item.find('div', class_='list-item-title')
                if title_node:
                    title_link = title_node.find('a')
            
            if not title_link:
                # One more try for any <a> in list-item-title
                title_node = item.find(class_='list-item-title')
                if title_node:
                    title_link = title_node.find('a')

            if not title_link:
                continue
                
            title_raw = title_link.text.strip()
            
            # Info node contains duration: <div class="info">... | 103 min</div>
            info_node = item.find('div', class_='info')
            duration_min = None
            if info_node:
                text = info_node.text
                match = re.search(r'(\d+)\s*min', text)
                if match:
                    duration_min = int(match.group(1))
            
            # Buttons for each screening: <a class="b24-button">...</a>
            buttons = item.find_all('a', class_='b24-button')
            
            for btn in buttons:
                # Hour is in <span class="b24-button__hour hour">13:00</span>
                hour_node = btn.find('span', class_='b24-button__hour')
                # Format is in <span class="b24-button__format format">2D NAP</span>
                format_node = btn.find('span', class_='b24-button__format')
                
                if not hour_node:
                    continue
                    
                time_str = hour_node.text.strip()
                format_raw = format_node.text.strip() if format_node else ""
                
                try:
                    hour, minute = map(int, time_str.split(':'))
                    starts_at = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
                except (ValueError, AttributeError):
                    continue
                
                language, tags = extract_language_and_tags(title_raw, format_raw)
                
                # Extract poster URL
                poster_url = None
                img_node = item.find('img', class_='b24-image') or item.find('img')
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
                    booking_url=btn.get('href'),
                    poster_url=poster_url
                ))
                
        return screenings
