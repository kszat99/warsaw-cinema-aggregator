import httpx
import asyncio
from bs4 import BeautifulSoup
import sys
import io

async def get_cinema_name(cid, client):
    # We'll try to find the cinema name by hitting the booking page or the main page with the ID
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # The name is often in a specific place. Let's look for common markers.
            # Sometimes it's in a script tag as 'cinemaName'
            import re
            match = re.search(r'cinemaName["\']:\s*["\'](.*?)["\']', resp.text)
            if match:
                return match.group(1)
            
            # Or in the title
            title = soup.title.string if soup.title else ""
            if "Cinema City" in title:
                # Often "Films in Cinema City X"
                clean_name = title.replace("Kino", "").replace("Filmy w", "").replace("Cinema City", "").replace("-", "").strip()
                return clean_name
                
            # Or in an h1
            h1 = soup.find('h1')
            if h1:
                return h1.text.strip()
                
            return "Unknown (200)"
        return f"Error {resp.status_code}"
    except Exception as e:
        return f"Ex: {e}"

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        # Range of potential Warsaw IDs
        print("Probing Cinema City IDs for Names...")
        for cid in range(1060, 1085):
            name = await get_cinema_name(cid, client)
            if "Error 404" not in name:
                print(f"ID {cid}: {name}")

if __name__ == "__main__":
    asyncio.run(main())
