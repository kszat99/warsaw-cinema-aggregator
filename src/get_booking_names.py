import httpx
import sys
import io

async def get_booking_name(cid, client):
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
            if not events: return f"ID {cid}: No events"
            
            booking_url = events[0].get('bookingLink')
            if not booking_url: return f"ID {cid}: No booking link"
            
            # Follow booking link
            resp_booking = await client.get(booking_url, headers=headers)
            html = resp_booking.text
            
            # Look for cinema name in the booking page
            # Usually it's in a header or a specific element
            if "Manufaktura" in html: name = "Manufaktura"
            elif "Zielona Góra" in html: name = "Zielona Góra"
            elif "Czerwona Droga" in html: name = "Toruń (Czerwona Droga)"
            elif "Plaza" in html: name = "Plaza (likely Poznań or Kraków)"
            elif "Mokotów" in html: name = "Mokotów"
            else:
                # Look for a <div> with a class that might contain the name
                import re
                match = re.search(r'cinemaName["\']:\s*["\'](.*?)["\']', html)
                if match:
                    name = match.group(1)
                else:
                    name = "Name not found in HTML"
            
            return f"ID {cid}: {name} | URL: {resp_booking.url}"
        return f"ID {cid}: HTTP {resp.status_code}"
    except Exception as e:
        return f"ID {cid}: Ex: {e}"

import asyncio

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        # Check candidate IDs
        for cid in ["1070", "1080", "1085"]:
            res = await get_booking_name(cid, client)
            print(res)

if __name__ == "__main__":
    asyncio.run(main())
