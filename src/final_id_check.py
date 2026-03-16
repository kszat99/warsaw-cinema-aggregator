import httpx
import sys
import io

async def check_name(cid, client):
    target_date = "2026-03-16"
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        data = resp.json()
        booking_url = data.get('body', {}).get('events', [])[0].get('bookingLink')
        
        resp_booking = await client.get(booking_url, headers=headers)
        text = resp_booking.text
        
        results = []
        if "Mokotów" in text: results.append("Mokotów")
        if "Manufaktura" in text: results.append("Manufaktura")
        if "Zielona Góra" in text: results.append("Zielona Góra")
        if "Arkadia" in text: results.append("Arkadia")
        
        return f"ID {cid}: {' & '.join(results) if results else 'NotFound'}"
    except:
        return f"ID {cid}: Error"

import asyncio

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for cid in ["1070", "1074", "1080", "1085"]:
            res = await check_name(cid, client)
            print(res)

if __name__ == "__main__":
    asyncio.run(main())
