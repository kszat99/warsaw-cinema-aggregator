import httpx
import asyncio
import json

async def check_raw_sadyba():
    # Sadyba is 1089
    target_date = "2026-03-10"
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/1089/at-date/{target_date}?attr=&lang=pl_PL"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.cinema-city.pl/'
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            events = data.get('body', {}).get('events', [])
            print(f"Sadyba 2026-03-10: Total {len(events)} raw events found in API")
            if events:
                for e in events[:2]:
                    print(e)

if __name__ == "__main__":
    asyncio.run(check_raw_sadyba())
