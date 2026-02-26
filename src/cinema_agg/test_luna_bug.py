import asyncio
import httpx
from bs4 import BeautifulSoup

async def test_luna_day(target_day="2026-02-21"):
    url = f"https://kinoluna.bilety24.pl/?b24_day={target_day}"
    print(f"Testing {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, follow_redirects=True)
        print(f"Status: {resp.status_code}")
        print(f"Final URL: {resp.url}")
        
        soup = BeautifulSoup(resp.text, 'lxml')
        items = soup.find_all('div', class_='list-item')
        print(f"Found {len(items)} 'list-item' containers")
        
        for i, item in enumerate(items):
            title = item.find('a', class_='b24-link text')
            if not title:
                title = item.find('div', class_='list-item-title')
            title_text = title.text.strip() if title else "NO TITLE"
            
            btns = item.find_all('a', class_='b24-button')
            print(f"  {i+1}. {title_text} - {len(btns)} buttons")

        # If 0 items, let's see what's there
        if len(items) == 0:
            with open("luna_debug.html", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print("Dumped HTML to luna_debug.html for inspection.")

if __name__ == "__main__":
    asyncio.run(test_luna_day())
