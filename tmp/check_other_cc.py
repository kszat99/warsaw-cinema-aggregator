import sys
import io
import httpx
import asyncio
from datetime import date
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def check_other_cc():
    target_date = "2026-03-05"
    ids = {
        "1087": "Galeria Mokotów",
        "1090": "Promenada",
        "1096": "Galeria Północna",
        "1091": "Janki",
        "1092": "Białołęka",
        "1093": "Zielonka"
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.cinema-city.pl/'
    }

    async with httpx.AsyncClient() as client:
        for cid, name in ids.items():
            url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                events = data.get('body', {}).get('events', [])
                print(f"{name} ({cid}): {len(events)} events")

if __name__ == "__main__":
    asyncio.run(check_other_cc())
