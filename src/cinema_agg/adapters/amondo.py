import re
from datetime import date, datetime
from typing import List
from bs4 import BeautifulSoup
import httpx

from .base import BaseAdapter
from ..models import Screening
from ..normalize import clean_title_for_search, normalize_title

class AmondoAdapter(BaseAdapter):
    def __init__(self, cinema_id: str, cinema_name: str, base_url: str):
        super().__init__(cinema_id=cinema_id, cinema_name=cinema_name, base_url=base_url)

    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        screenings = []
        try:
            response = await client.get(self.base_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the tabs container
            tabs_container = soup.find('div', class_='fw-tabs')
            if not tabs_container:
                return screenings
                
            ul = tabs_container.find('ul')
            if not ul:
                return screenings
                
            # Extract dates from the ul li elements
            date_strings = [li.text.strip() for li in ul.find_all('li')]
            
            # Find the corresponding panels (divs that are direct children of tabs_container)
            panels = [div for div in tabs_container.find_all('div', recursive=False)]
            
            for i, panel in enumerate(panels):
                if i >= len(date_strings):
                    break
                    
                date_str = date_strings[i]
                
                # Try to parse the day from date_str (e.g. "Śr, 11.03.")
                day_match = re.search(r'\b(\d{1,2})\.', date_str)
                if not day_match:
                    continue
                    
                day_num = int(day_match.group(1))
                
                # If this panel is for our target date
                if day_num == target_date.day:
                    # Find all ticketing links - Amondo uses both kicket.com and biletomat.pl
                    links = panel.find_all('a', href=re.compile(r'(kicket\.com|biletomat\.pl)/embeddables/repertoire\?organizerId=(\d+)&showId=(\d+)'))
                    
                    for link in links:
                        href = link['href']
                        
                        movie_container = link.find_parent('div', class_=re.compile(r'movie|event|row', re.I))
                        if not movie_container:
                            continue
                            
                        # Extract title
                        title_elem = movie_container.find(['h2', 'h3'])
                        if not title_elem:
                            continue
                        title_raw = title_elem.text.strip()
                        
                        # Extract time
                        time_patterns = movie_container.find_all(string=re.compile(r'\d{1,2}:\d{2}'))
                        if not time_patterns:
                            continue
                        
                        time_str = time_patterns[0].strip()
                        time_match_reg = re.search(r'(\d{1,2}):(\d{2})', time_str)
                        if not time_match_reg:
                            continue
                            
                        hour = int(time_match_reg.group(1))
                        minute = int(time_match_reg.group(2))
                        
                        starts_at = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
                        
                        title_norm = clean_title_for_search(title_raw)
                        
                        screenings.append(
                            Screening(
                                cinema_id=self.cinema_id,
                                cinema_name=self.cinema_name,
                                title_raw=title_raw,
                                title_norm=title_norm,
                                starts_at=starts_at,
                                booking_url=href
                            )
                        )
                        
        except Exception as e:
            import traceback
            print(f"Error fetching Amondo for {target_date}: {e}")
            traceback.print_exc()
            
        return screenings
