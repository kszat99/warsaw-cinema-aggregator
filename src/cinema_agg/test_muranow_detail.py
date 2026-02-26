import asyncio
import httpx
from bs4 import BeautifulSoup
import re

async def test_muranow_detail():
    url = "https://kinomuranow.pl/film/la-grazia"
    print(f"Testing {url}")
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=20.0)
        resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, 'lxml')
    text = soup.get_text()
    
    # Save a snippet of text for inspection
    with open("muranow_detail_text.txt", "w", encoding="utf-8") as f:
        f.write(text)
    
    print("Searching for duration...")
    dur_match = re.search(r'Czas trwania\s+(\d+)\s*min', text, re.IGNORECASE)
    if dur_match:
        print(f"Found duration: {dur_match.group(1)}")
    else:
        print("Duration not found with current regex.")

    print("Searching for language...")
    lang_match = re.search(r'Język\s+([^|\n\r]+)', text, re.IGNORECASE)
    if lang_match:
        print(f"Found language: {lang_match.group(1).strip()}")
    else:
        print("Language not found.")

if __name__ == "__main__":
    asyncio.run(test_muranow_detail())
