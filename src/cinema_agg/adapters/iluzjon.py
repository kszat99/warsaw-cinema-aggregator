import httpx
import re
from datetime import date, datetime
from typing import List
from ..models import Screening
from .base import BaseAdapter
from ..normalize import normalize_title
from bs4 import BeautifulSoup

class IluzjonAdapter(BaseAdapter):
    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        # Iluzjon usually has one big schedule page. 
        # We fetch it once but filter results for target_date.
        # This is a bit inefficient if called per-day, but manageable.
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        
        try:
            resp = await client.get(self.base_url, headers=headers)
            if resp.status_code != 200:
                return []
            html = resp.text
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        screenings = []
        
        # Structure looks like:
        # <div class="day-repertuar"> <h3>... 04.03 ...</h3> ... </div>
        # Or similar. Let's look for date headers.
        
        # Extract all date blocks
        # Looking at previous debug: <span class="hour"><a href="...">20:00 - Persepolis</a></span>
        # We need to find which day this belongs to.
        
        # Typically sites like this have headers for days:
        # <h2>Środa, 04.03</h2>
        
        day_blocks = soup.select(".repertuar-day, .day-box, .repertuar_list") 
        # If no specific containers, we might have to iterate siblings of <h3> dates.
        
        # Let's try a simpler approach if the HTML is regular:
        # Find all <h3> that match DD.MM.YYYY or DD.MM
        for h3 in soup.find_all(["h3", "h2", "h4"]):
            date_text = h3.get_text(strip=True)
            # Match formats like "04.03", "04.03.2026", "Środa, 4 marca"
            # Polish month names
            month_map = {
                "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
                "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12
            }
            
            found_date = None
            
            # Pattern 1: DD.MM or DD.MM.YYYY
            match = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?', date_text)
            if match:
                d = int(match.group(1))
                m = int(match.group(2))
                y = int(match.group(3)) if match.group(3) else target_date.year
                found_date = date(y, m, d)
            else:
                # Pattern 2: "4 marca"
                for m_name, m_num in month_map.items():
                    if m_name in date_text.lower():
                        match = re.search(rf'(\d{{1,2}})\s+{m_name}', date_text.lower())
                        if match:
                            d = int(match.group(1))
                            found_date = date(target_date.year, m_num, d)
                            break
            
            if found_date == target_date:
                # This is our day! Now find all screenings until the next date header
                # Screenings are in <span class="hour">
                parent = h3.parent
                # Sometimes headers are outside the container. Scan siblings.
                current = h3.find_next_sibling()
                while current and current.name not in ["h2", "h3", "h4"]:
                    # Search inside current for hours
                    for hour_span in current.select(".hour"):
                        link = hour_span.find("a")
                        if not link: continue
                        
                        text = link.get_text(separator=" ", strip=True)
                        # Text is like "20:00 - Persepolis"
                        m_time = re.match(r'(\d{2}:\d{2})\s*-\s*(.*)', text)
                        if m_time:
                            time_str = m_time.group(1)
                            title_raw = m_time.group(2)
                            
                            starts_at = datetime.combine(target_date, datetime.strptime(time_str, "%H:%M").time())
                            
                            # Language tags
                            lang = "org"
                            if "napisy" in title_raw.lower() or "sub" in title_raw.lower():
                                lang = "nap"
                            
                            booking_url = link.get("href", "")
                            if booking_url.startswith("/"):
                                booking_url = "https://www.iluzjon.fn.org.pl" + booking_url
                                
                            screenings.append(Screening(
                                cinema_id=self.cinema_id,
                                cinema_name=self.cinema_name,
                                title_raw=title_raw,
                                title_norm=normalize_title(title_raw),
                                starts_at=starts_at,
                                duration_min=None,
                                language=lang,
                                tags=[],
                                booking_url=booking_url
                            ))
                    current = current.find_next_sibling()
                
        return screenings
