import httpx
import asyncio
import sys
import json

# Ensure UTF-8 output on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        url = "https://multikino.pl/api/microservice/showings/cinemas"
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            warsaw_cinemas = []
            for group in data.get("result", []):
                for cinema in group.get("cinemas", []):
                    name = cinema.get("cinemaName", "")
                    warsaw_cinemas.append({
                        "name": name,
                        "id": cinema.get("cinemaId"),
                        "url": cinema.get("whatsOnUrl")
                    })
            print(json.dumps(warsaw_cinemas, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
