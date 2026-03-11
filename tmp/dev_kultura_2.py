import httpx
from bs4 import BeautifulSoup
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def check_kultura_base():
    url = "https://www.kinokultura.pl/repertuar/"
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        r = await client.get(url)
        soup = BeautifulSoup(r.text, 'lxml')
        
        # Look for movie elements
        movies = soup.find_all(class_=lambda c: c and 'movie' in c)
        print(f"Found {len(movies)} movie elements")
        
        # Try to find exactly what we need
        import re
        iframes = re.findall(r'<iframe[^>]*src=["\']([^"\']+)["\']', r.text, re.I)
        print("iframes:")
        for iframe in iframes:
            print(f"- {iframe}")

if __name__ == '__main__':
    import asyncio
    asyncio.run(check_kultura_base())
