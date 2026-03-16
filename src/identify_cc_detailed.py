import httpx
import asyncio
import sys
import io

async def check_id_full(cid, client):
    # Try to find the name more reliably
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    try:
        resp = await client.get(url, headers=headers)
        # Look for the selected cinema in the form data or such
        # We can also check the repertoire API for titles that might give a clue
        return (cid, resp.status_code, resp.text)
    except:
        return (cid, 0, "")

async def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        test_ids = [str(x) for x in range(1060, 1100)]
        tasks = [check_id_full(cid, client) for cid in test_ids]
        results = await asyncio.gather(*tasks)
        
        for cid, status, text in results:
            if status == 200 or status == 404:
                # Look for distinctive strings but exclude the common ones in 404
                # If it's a "real" page, it should have the cinema name near "Kup bilet"
                import re
                match = re.search(r'<title>(.*?)</title>', text)
                title = match.group(1) if match else ""
                
                # If we are lucky, there's a specific tag
                name_match = re.search(r'cinemaName["\']:\s*["\'](.*?)["\']', text)
                name = name_match.group(1) if name_match else "???"
                
                if "Strona główna" not in title or name != "???":
                    print(f"ID {cid} ({status}): Name='{name}' Title='{title}'")

if __name__ == "__main__":
    asyncio.run(main())
