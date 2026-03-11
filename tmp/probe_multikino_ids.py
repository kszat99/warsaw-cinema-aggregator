import httpx
import re
import asyncio
import sys

# Ensure UTF-8 output on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def get_multikino_id(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                print(f"Failed to fetch {url}: {resp.status_code}")
                return None
            
            # The ID is often in a script tag or as a data attribute
            # Look for /api/microservice/showings/cinemas/(\d{4})/films
            match = re.search(r'cinemas/(\d{4})/films', resp.text)
            if match:
                return match.group(1)
            
            # Look for "cinemaId":"00XX"
            match = re.search(r'"cinemaId"\s*:\s*"(00\d{2})"', resp.text)
            if match:
                return match.group(1)
                
            # Or look for window.__INITIAL_STATE__ or similar
            # Sometimes it's just in the URL if we are lucky, but here it's slug-based.
            
            return None
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

async def main():
    urls = {
        "Targówek": "https://multikino.pl/repertuar/warszawa-targowek",
        "Reduta": "https://multikino.pl/repertuar/warszawa-g-city-reduta",
        "Wola Park": "https://multikino.pl/repertuar/warszawa-wola",
        "Młociny": "https://multikino.pl/repertuar/warszawa-mlociny",
        "Złote Tarasy": "https://multikino.pl/repertuar/warszawa-zlote-tarasy"
    }
    
    for name, url in urls.items():
        cinema_id = await get_multikino_id(url)
        print(f"{name}: {cinema_id} ({url})")

if __name__ == "__main__":
    asyncio.run(main())
