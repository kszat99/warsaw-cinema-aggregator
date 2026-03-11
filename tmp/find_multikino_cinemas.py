import httpx
import json
import re
import sys

# Ensure UTF-8 output on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def find_cinemas():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient() as client:
        # Multikino often uses an API to list cinemas
        # Let's try to find it in the Zlote Tarasy page source first
        url = "https://www.multikino.pl/repertuar/warszawa-zlote-tarasy/teraz-gramy"
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            # Look for "id":"0013" in a larger JSON block
            # Or look for any 4-digit ID patterns
            ids = re.findall(r'"id"\s*:\s*"(00\d{2})"', resp.text)
            print(f"Found IDs in source: {set(ids)}")
            
            # Look for script tags with cinema data
            data_matches = re.findall(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', resp.text)
            for dm in data_matches:
                try:
                    state = json.loads(dm)
                    # Traverse the state to find cinemas
                    # This depends on the internal structure
                    pass
                except:
                    pass

        # Try common API endpoints
        api_urls = [
            "https://multikino.pl/api/microservice/showings/cinemas",
            "https://multikino.pl/api/microservice/cinemas/list"
        ]
        for api_url in api_urls:
            try:
                r = await client.get(api_url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    print(f"Data from {api_url}: {json.dumps(data, indent=2)[:500]}...")
            except:
                pass

if __name__ == "__main__":
    import asyncio
    asyncio.run(find_cinemas())
