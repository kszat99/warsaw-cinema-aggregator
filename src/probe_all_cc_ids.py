import httpx
import asyncio
import sys
import io

async def probe_showtime(cid, client, target_date):
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            films = {f['id']: f['name'] for f in data.get('body', {}).get('films', [])}
            events = data.get('body', {}).get('events', [])
            
            for e in events:
                time = e.get('eventDateTime').split('T')[1][:5]
                # Check for "Bez wyjścia" at 18:40
                if time == "18:40":
                    f_name = films.get(e['filmId'], "")
                    if "Bez wyj" in f_name:
                        return cid, f_name
        return None
    except:
        return None

async def get_cinema_name(cid, client):
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        # Even if 404, look for clues
        import re
        match = re.search(r'cinemaName["\']:\s*["\'](.*?)["\']', resp.text)
        if match: return match.group(1)
        
        match = re.search(r'<title>(.*?)</title>', resp.text)
        if match:
            t = match.group(1)
            if "Strona główna" not in t:
                return t.replace("Cinema City ", "").replace("Kino ", "").strip()
        return "Unknown"
    except:
        return "Error"

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    target_date = "2026-03-16"
    print(f"Searching for 'Bez wyjścia' at 18:40 on {target_date}...")
    
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        test_ids = [str(x) for x in range(1010, 1150)]
        probe_tasks = [probe_showtime(cid, client, target_date) for cid in test_ids]
        matches = await asyncio.gather(*probe_tasks)
        matches = [m for m in matches if m]
        
        if not matches:
            print("No matches found.")
            return
            
        print(f"Found {len(matches)} potential cinemas. Verifying names...")
        for cid, film in matches:
            name = await get_cinema_name(cid, client)
            print(f"ID {cid}: {name} (Film: {film})")

if __name__ == "__main__":
    asyncio.run(main())
