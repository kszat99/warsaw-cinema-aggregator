import httpx
import asyncio
import sys
import io

async def get_count(cid, client):
    target_date = "2026-03-16"
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            events = data.get('body', {}).get('events', [])
            return cid, len(events)
        return cid, -1
    except:
        return cid, -2

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(timeout=10) as client:
        print("Final screening count check (1060-1100)...")
        tasks = [get_count(str(cid), client) for cid in range(1060, 1101)]
        results = await asyncio.gather(*tasks)
        for cid, count in results:
            if count > 0:
                print(f"ID {cid}: {count} screenings")

if __name__ == "__main__":
    asyncio.run(main())
