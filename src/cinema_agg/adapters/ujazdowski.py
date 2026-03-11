import re
from datetime import date, datetime
from typing import List, Set
from bs4 import BeautifulSoup
import httpx
import calendar

from .base import BaseAdapter
from ..models import Screening
from ..normalize import clean_title_for_search, normalize_title


class UjazdowskiAdapter(BaseAdapter):
    def __init__(self, cinema_id: str, cinema_name: str, base_url: str):
        # base_url is typically 'https://u-jazdowski.pl/kino/repertuar'
        super().__init__(cinema_id=cinema_id, cinema_name=cinema_name, base_url=base_url)
        self.portal_url = "https://bilety.u-jazdowski.pl/MSI/mvc/pl"


    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        """
        Resilient Hybrid Approach:
        1. Primary: Scrape u-jazdowski.pl/kino/repertuar for the "official" screenings (times, titles, detail links).
           This is reachable from CI and only includes actual movies.
        2. Secondary: Attempt to reach the ticketing portal (bilety.u-jazdowski.pl) to get specific booking IDs.
           If it fails (e.g. in CI), we fall back to the detail links from step 1.
        """
        screenings: List[Screening] = []
        
        # 1. Fetch from Main Site (Primary Source)
        try:
            ts = int(calendar.timegm(target_date.timetuple()))
            url = f"{self.base_url}?ut={ts}"
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Cards: a.event-list-day-box
            cards = soup.find_all('a', class_='event-list-day-box')
            for card in cards:
                # Title
                title_el = card.find('em')
                if not title_el:
                    continue
                title_raw = title_el.get_text(strip=True)
                title_raw = re.sub(r'\s*Premiera!\s*$', '', title_raw, flags=re.I).strip()
                title_norm = normalize_title(title_raw)
                
                # Showtime (e.g. 16:30)
                time_el = card.find('div', class_='hours')
                if not time_el:
                    continue
                time_str = time_el.get_text(strip=True) # "16:30"
                match = re.search(r'(\d{1,2}):(\d{2})', time_str)
                if not match:
                    continue
                
                hour = int(match.group(1))
                minute = int(match.group(2))
                starts_at = datetime(target_date.year, target_date.month, target_date.day, hour, minute)
                
                # Detail Link (Fallback Booking URL)
                detail_path = card.get('href', '')
                from urllib.parse import urljoin
                detail_url = urljoin("https://u-jazdowski.pl", detail_path)
                
                screenings.append(
                    Screening(
                        cinema_id=self.cinema_id,
                        cinema_name=self.cinema_name,
                        title_raw=title_raw,
                        title_norm=title_norm,
                        starts_at=starts_at,
                        booking_url=detail_url # Default to detail page
                    )
                )
        except Exception as e:
            print(f"Error fetching Ujazdowski from main site for {target_date}: {e}")
            return [] # If main site is down, we have nothing

        if not screenings:
            return []

        # 2. Attempt Portal Enhancement (Secondary Source)
        try:
            # We use a shorter timeout for the portal in CI if possible, or just catch the timeout
            response = await client.get(self.portal_url, follow_redirects=True, timeout=10.0) 
            response.raise_for_status()
            portal_soup = BeautifulSoup(response.text, 'html.parser')
            
            # Map of normalized_title + time -> booking_url
            portal_map = {}
            # The portal uses .list-group-item.visible-md
            items = portal_soup.find_all('div', class_=lambda c: c and 'list-group-item' in c and 'visible-md' in c)
            for item in items:
                p_title_el = item.find('div', class_='event-title')
                if not p_title_el: continue
                p_title_norm = normalize_title(p_title_el.get_text(strip=True))
                
                badges = item.find_all('a', class_=re.compile(r'badge'))
                for badge in badges:
                    badge_text = badge.get_text(separator=' ', strip=True)
                    m = re.search(r'(\d{1,2})\s+([a-ząćęłńóśźż]{3})\s+(\d{1,2}):(\d{2})', badge_text, re.I)
                    if m:
                        p_day = int(m.group(1))
                        # We only care if it's our target date
                        if p_day != target_date.day: continue
                        
                        p_time = f"{int(m.group(3)):02d}:{int(m.group(4)):02d}"
                        b_url = badge.get('href', '')
                        if b_url:
                            b_url = urljoin(self.portal_url, b_url)
                            portal_map[(p_title_norm, p_time)] = b_url
            
            # Update screenings with portal links if found
            for s in screenings:
                key = (s.title_norm, s.starts_at.strftime("%H:%M"))
                if key in portal_map:
                    s.booking_url = portal_map[key]
                    
        except Exception as e:
            # Silently fail enhancement - we already have the screenings from the main site
            print(f"Ujazdowski portal enhancement skipped for {target_date} (likely blocked in CI): {e}")
            
        return screenings
