import httpx
import asyncio
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def scan():
    headers = {
        'User-Agent': 'Mozilla/5.0'
    }
    async with httpx.AsyncClient(timeout=10) as client:
        for i in range(1085, 1110):
            url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{i}/at-date/2026-03-05?attr=&lang=pl_PL"
            try:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    films = data.get('body', {}).get('films', [])
                    events = data.get('body', {}).get('events', [])
                    if events:
                        # Extract cinema name by checking the booking link if possible or site
                        print(f"Cinema {i}: found events")
            except:
                pass

if __name__ == "__main__":
    asyncio.run(scan())
