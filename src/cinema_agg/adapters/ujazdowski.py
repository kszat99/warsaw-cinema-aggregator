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

    async def _get_authorized_titles(self, target_date: date, client: httpx.AsyncClient) -> Set[str]:
        """
        Scrapes the cinema's official repertoire page to get a list of authorized movie titles for the day.
        """
        authorized_titles = set()
        try:
            # Shift to midnight of the target date for the timestamp
            ts = int(calendar.timegm(target_date.timetuple()))
            
            url = f"{self.base_url}?ut={ts}"
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # a.event-list-day-box contains the movie cards for the day specified by ?ut
            cards = soup.find_all('a', class_='event-list-day-box')
            for card in cards:
                title_el = card.find('em')
                if title_el:
                    title = title_el.get_text(strip=True)
                    # Clean title (remove trailing Premiera! if present)
                    title = re.sub(r'\s*Premiera!\s*$', '', title, flags=re.I).strip()
                    normalized = normalize_title(title)
                    authorized_titles.add(normalized)
            
            # If no cards found, maybe they use a different selector for mobile or different layout
            if not authorized_titles:
                # Fallback: look for generic titles in high-priority headings if cards are missing
                pass
                    
        except Exception as e:
            print(f"Error fetching authorized titles from Ujazdowski cinema page: {e}")
            
        return authorized_titles

    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        """
        Hybrid approach:
        1. Get authorized titles from the cinema page (u-jazdowski.pl/kino/repertuar).
        2. Fetch all events from the ticketing portal (bilety.u-jazdowski.pl).
        3. Only include portal events that match an authorized title.
        """
        screenings = []
        
        # 1. Get authorized titles
        auth_titles = await self._get_authorized_titles(target_date, client)
        if not auth_titles:
            # If the cinema page returned nothing, we don't return anything to avoid false positives
            return screenings

        # 2. Fetch from portal
        try:
            response = await client.get(self.portal_url, follow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # The portal uses an MSI system. Events are in .list-group-item.visible-md
            items = soup.find_all('div', class_=lambda c: c and 'list-group-item' in c and 'visible-md' in c)
            
            for item in items:
                title_elem = item.find('div', class_='event-title')
                if not title_elem:
                    continue
                    
                title_raw = title_elem.get_text(separator=' ', strip=True)
                title_raw = re.sub(r'\s*Premiera!\s*$', '', title_raw, flags=re.I).strip()
                title_norm = normalize_title(title_raw)
                
                # Filter: title must be in our authorized list
                if auth_titles and title_norm not in auth_titles:
                    continue
                
                # Find badges for the specific date
                badges = item.find_all('a', class_=re.compile(r'badge'))
                for badge in badges:
                    # The badge text is like "11 mar 16:30\n        Przejdź do wyboru..."
                    badge_text = badge.get_text(separator=' ', strip=True)
                    # We need "11 mar 16:30"
                    match = re.search(r'(\d{1,2})\s+([a-ząćęłńóśźż]{3})\s+(\d{1,2}):(\d{2})', badge_text, re.I)
                    if not match:
                        continue
                        
                    day_num = int(match.group(1))
                    month_str = match.group(2).lower()
                    hour = int(match.group(3))
                    minute = int(match.group(4))
                    
                    # Simple month mapping for Polish
                    months = {
                        'sty': 1, 'lut': 2, 'mar': 3, 'kwi': 4, 'maj': 5, 'cze': 6,
                        'lip': 7, 'sie': 8, 'wrz': 9, 'paź': 10, 'lis': 11, 'gru': 12
                    }
                    month_num = months.get(month_str[:3])
                    if not month_num:
                        continue
                        
                    # Check if this badge is for our target date
                    # Note: We assume the year is the current year or next (for December/January transition)
                    year = target_date.year
                    if month_num == 1 and target_date.month == 12:
                        year += 1
                    elif month_num == 12 and target_date.month == 1:
                        year -= 1
                        
                    if day_num == target_date.day and month_num == target_date.month:
                        starts_at = datetime(year, month_num, day_num, hour, minute)
                        
                        # Booking URL
                        booking_url = badge.get('href', '')
                        if booking_url and not booking_url.startswith('http'):
                            # Resolve relative URL
                            from urllib.parse import urljoin
                            booking_url = urljoin(self.portal_url, booking_url)
                            
                        screenings.append(
                            Screening(
                                cinema_id=self.cinema_id,
                                cinema_name=self.cinema_name,
                                title_raw=title_raw,
                                title_norm=title_norm,
                                starts_at=starts_at,
                                booking_url=booking_url
                            )
                        )
                        
        except Exception as e:
            print(f"Error fetching Ujazdowski from portal: {e}")
            
        return screenings
