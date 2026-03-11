import httpx
import asyncio
import sys

# Ensure UTF-8 output on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def probe_id(id_str, target_date_str, client):
    url = f"https://www.multikino.pl/api/microservice/showings/cinemas/{id_str}/films"
    params = {
        "showingDate": target_date_str,
        "minEmbargoLevel": "3",
        "includesSession": "true",
        "includeSessionAttributes": "true"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    try:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            if "result" in data and len(data["result"]) > 0:
                # We found a valid cinema with screenings!
                # Now we need to find its name.
                # Usually there's no name in this response, but maybe in a configuration API.
                return id_str, True
    except:
        pass
    return id_str, False

async def main():
    target_date_str = "2026-03-04T00:00:00"
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = []
        for i in range(1, 101):
            id_str = f"{i:04d}"
            tasks.append(probe_id(id_str, target_date_str, client))
        
        results = await asyncio.gather(*tasks)
        valid_ids = [id_str for id_str, valid in results if valid]
        print(f"Valid IDs found: {valid_ids}")

if __name__ == "__main__":
    asyncio.run(main())
