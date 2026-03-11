import httpx
import re
import json
from datetime import date, datetime
from typing import List
from ..models import Screening
from .base import BaseAdapter
from ..normalize import normalize_title

class HeliosAdapter(BaseAdapter):
    async def fetch_screenings(self, target_date: date, client: httpx.AsyncClient) -> List[Screening]:
        # target_date as YYYY-MM-DD
        # Note: helios.pl/warszawa/kino-helios-blue-city/repertuar contains all data in Nuxt state
        url = self.base_url
        if not url.endswith("repertuar"):
            # Redirects/Mapping handle this but let's be safe
            pass

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            html = resp.text
        except Exception:
            return []

        # Try Nuxt parsing first as it's more comprehensive
        target_iso = target_date.isoformat()
        screenings = self._parse_nuxt(html, target_iso)
        
        if not screenings:
            # Fallback to old regex for server-rendered 今日 repertoire
            screenings = self._parse_html_regex(html, target_date)
            
        return screenings

    def _extract_obj(self, text: str, start_idx: int) -> str:
        count = 0
        end = start_idx
        started = False
        for i in range(start_idx, len(text)):
            char = text[i]
            if char in '{[':
                count += 1
                started = True
            elif char in '}]':
                count -= 1
            
            if started and count == 0:
                end = i + 1
                break
        return text[start_idx:end]

    def _parse_nuxt(self, html: str, target_date: str) -> List[Screening]:
        # Extract Nuxt state
        match = re.search(r'window\.__NUXT__=\(function\((.*?)\)\{.*?return (.*?)\}\((.*?)\)\);', html, re.DOTALL)
        if not match: return []

        var_names = [v.strip() for v in match.group(1).split(',')]
        body = match.group(2)
        var_values_raw = match.group(3)

        try:
            cleaned_vals = var_values_raw.replace('void 0', 'null').replace('undefined', 'null')
            values = json.loads("[" + cleaned_vals + "]")
        except: return []
            
        mapping = dict(zip(var_names, values))
        
        def gv(k):
            k = k.strip('"')
            return mapping.get(k, k)

        title_map = {}
        
        # 1. Build Title Map from repertoire list
        repert_idx = body.find('repertoire:{')
        if repert_idx != -1:
            repert_obj = self._extract_obj(body, repert_idx + 10)
            list_idx = repert_obj.find('list:[')
            if list_idx != -1:
                list_str = self._extract_obj(repert_obj, list_idx + 5)
                for item_m in re.finditer(r'\{[^{}]*?(id|sourceId|_id):(?P<id>[a-zA-Z0-9"]+).*?(title|name):(?P<title>[a-zA-Z0-9]+).*?\}', list_str):
                    title = gv(item_m.group('title'))
                    if not isinstance(title, str) or title.lower() in ["zwiastun", "trailer"]: continue
                    id_val = gv(item_m.group('id'))
                    title_map[str(id_val)] = title
                    title_map[item_m.group('id').strip('"')] = title

                # Reverse search order for title/id
                for item_m in re.finditer(r'\{[^{}]*?(title|name):(?P<title>[a-zA-Z0-9]+).*?(id|sourceId|_id):(?P<id>[a-zA-Z0-9"]+).*?\}', list_str):
                    title = gv(item_m.group('title'))
                    if not isinstance(title, str) or title.lower() in ["zwiastun", "trailer"]: continue
                    id_val = gv(item_m.group('id'))
                    title_map[str(id_val)] = title
                    title_map[item_m.group('id').strip('"')] = title

            # 2. Extract Screenings
            scr_idx = repert_obj.find('screenings:{')
            if scr_idx != -1:
                scr_obj = self._extract_obj(repert_obj, scr_idx + 11)
                date_key = f'"{target_date}":'
                date_start = scr_obj.find(date_key)
                if date_start != -1:
                    date_block = self._extract_obj(scr_obj, date_start + len(date_key))
                    
                    results = []
                    # Cinema ID var is usually 'c' in Helios Nuxt
                    cinema_source_id = gv('c') or "4ca060df-c4f2-4157-8905-bf46527aae58"
                    
                    for mblock in re.finditer(r'(?P<key>[a-zA-Z0-9]+):\{screenings:\[(?P<items>.*?)\]\}', date_block):
                        key = mblock.group('key')
                        title = title_map.get(key, "Unknown")
                        if title == "Unknown" and key.startswith('m'):
                            title = title_map.get(key[1:], "Unknown")
                        
                        if title == "Unknown": continue # Skip unknown movies if they are noise
                        
                        items_raw = mblock.group('items')
                        for item in re.finditer(r'\{timeFrom:(?P<time>[a-zA-Z0-9]+),.*?sourceId:(?P<sid>[a-zA-Z0-9"]+),', items_raw):
                            t_val = gv(item.group('time'))
                            s_val = gv(item.group('sid'))
                            
                            try:
                                # t_val is "YYYY-MM-DD HH:MM:SS"
                                starts_at = datetime.strptime(t_val, "%Y-%m-%d %H:%M:%S")
                            except:
                                continue
                                
                            item_lower = item.group(0).lower()
                            lang = "org"
                            if "napisy" in item_lower: lang = "nap"
                            elif "dubbing" in item_lower: lang = "dub"
                            
                            tags = []
                            if "3d" in item_lower: tags.append("3D")
                            if "2d" in item_lower: tags.append("2D")
                            
                            results.append(Screening(
                                cinema_id=self.cinema_id,
                                cinema_name=self.cinema_name,
                                title_raw=title,
                                title_norm=normalize_title(title),
                                starts_at=starts_at,
                                duration_min=None,
                                language=lang,
                                tags=tags,
                                booking_url=f"https://bilety.helios.pl/screen/{s_val}?cinemaId={cinema_source_id}"
                            ))
                    return results
        return []

    def _parse_html_regex(self, html: str, target_date: date) -> List[Screening]:
        # Regex to match the ticket links and their descriptive titles in aria-label
        # aria-label="Kup bilet na &quot;Film&quot;, seans o 15:00 (4 marca 2026), 2D, napisy"
        pattern = re.compile(
            r'aria-label="Kup bilet na &quot;(?P<title>.*?)&quot;, seans o (?P<time>\d{2}:\d{2}) \((?P<day>\d{1,2}) (?P<month>[a-zżźćńółęąś]+) (?P<year>\d{4})\), (?P<desc>.*?)"'
            r'\s*href="(?P<url>https://bilety\.helios\.pl/screen/[^"]+)"'
        )
        
        month_map = {
            "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
            "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12
        }
        
        screenings = []
        for match in pattern.finditer(html):
            title_raw = match.group("title")
            time_str = match.group("time")
            day = int(match.group("day"))
            month_name = match.group("month")
            year = int(match.group("year"))
            desc = match.group("desc")
            booking_url = match.group("url").replace("&amp;", "&")
            
            month = month_map.get(month_name)
            if not month: continue
                
            try:
                starts_at = datetime(year, month, day, int(time_str.split(":")[0]), int(time_str.split(":")[1]))
                if starts_at.date() != target_date: continue
            except ValueError: continue
            
            lang = "org"
            tags = []
            desc_lower = desc.lower()
            if "napisy" in desc_lower: lang = "nap"
            elif "dubbing" in desc_lower: lang = "dub"
            elif "lektor" in desc_lower: lang = "lek"
                
            if "3d" in desc_lower: tags.append("3D")
            elif "2d" in desc_lower: tags.append("2D")
                
            if "ua" in desc_lower or "ukraińsku" in desc_lower: tags.append("UA")
                
            screenings.append(Screening(
                cinema_id=self.cinema_id,
                cinema_name=self.cinema_name,
                title_raw=title_raw,
                title_norm=normalize_title(title_raw),
                starts_at=starts_at,
                duration_min=None,
                language=lang,
                tags=tags,
                booking_url=booking_url
            ))
        return screenings
