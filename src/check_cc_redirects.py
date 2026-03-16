import httpx
import sys
import io

async def check_city(cid, client):
    # Try the buy-tickets URL which often redirects to the cinema page
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        # Check URL path
        path = resp.url.path
        return f"ID {cid} -> {resp.url}"
    except Exception as e:
        return f"ID {cid} -> Error: {e}"

import asyncio

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        # Check 1080, 1085, and maybe 1104
        for cid in ["1070", "1074", "1080", "1085", "1104"]:
            res = await check_city(cid, client)
            print(res)

if __name__ == "__main__":
    asyncio.run(main())
