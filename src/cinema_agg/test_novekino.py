import asyncio
import httpx
from bs4 import BeautifulSoup

async def test_novekino():
    # Test Wisla
    base_url = "https://wisla.novekino.pl/MSI/mvc/pl"
    # Alternative URL observed in screenshots earlier
    alt_url = f"{base_url}/Home/Repertoire?sort=Date&date=2026-02-18&datestart=0"
    
    print(f"Testing {alt_url}")
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(alt_url, follow_redirects=True)
            print(f"Status: {resp.status_code}")
            soup = BeautifulSoup(resp.text, 'lxml')
            items = soup.find_all('div', class_='film_item')
            print(f"Found {len(items)} film items")
            if len(items) > 0:
                print("First title:", items[0].find('div', class_='film_title').text.strip())
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_novekino())
