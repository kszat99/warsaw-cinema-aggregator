import asyncio
import httpx
from datetime import date

async def inspect_cc():
    cinema_id = "1088" # Arkadia
    target_date = date.today()
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cinema_id}/at-date/{target_date.isoformat()}?attr=&lang=pl_PL"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.cinema-city.pl/'
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        data = resp.json()
        films = data.get('body', {}).get('films', [])
        if films:
            print(f"Sample film data fields: {films[0].keys()}")
            print(f"Sample poster link: {films[0].get('posterLink')}")
            # Sometimes it's 'poster' or 'image'
            for film in films[:3]:
                print(f"\nFilm: {film.get('name')}")
                for k, v in film.items():
                    if 'http' in str(v) or 'jpg' in str(v) or 'png' in str(v):
                        print(f"  {k}: {v}")

if __name__ == "__main__":
    asyncio.run(inspect_cc())
