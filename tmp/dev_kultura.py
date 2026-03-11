import httpx
from bs4 import BeautifulSoup
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def check_kultura():
    url = "https://kinokultura.bilety24.pl/"
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        r = await client.get(url)
        print("Status", r.status_code)
        
        soup = BeautifulSoup(r.text, 'lxml')
        items = soup.find_all('div', class_='list-item')
        print(f"Found {len(items)} list-item elements")
        
        # Check standard bilety24 params
        r2 = await client.get(url + "?b24_day=2026-03-05")
        print("Status with day param", r2.status_code)
        soup2 = BeautifulSoup(r2.text, 'lxml')
        items2 = soup2.find_all('div', class_='list-item')
        print(f"Found {len(items2)} list-item elements with param")

if __name__ == '__main__':
    import asyncio
    asyncio.run(check_kultura())
