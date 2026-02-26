import asyncio
import httpx
from datetime import date

async def inspect_multikino():
    cinema_id = "0040" # Młociny
    target_date = date.today()
    
    client = httpx.AsyncClient(follow_redirects=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    
    api_url = f"https://www.multikino.pl/api/microservice/showings/cinemas/{cinema_id}/films"
    target_datetime_str = target_date.strftime("%Y-%m-%dT00:00:00")
    params = {
        "showingDate": target_datetime_str,
        "minEmbargoLevel": "3",
        "includesSession": "true",
        "includeSessionAttributes": "true"
    }
    
    resp = await client.get(api_url, params=params, headers=headers)
    await client.aclose()
    data = resp.json()
    
    films = data.get("result", [])
    if films:
        print(f"Sample film data fields: {films[0].keys()}")
        for film in films[:3]:
            print(f"\nFilm: {film.get('filmTitle')}")
            for k, v in film.items():
                if 'http' in str(v) or 'jpg' in str(v) or 'png' in str(v):
                    print(f"  {k}: {v}")

if __name__ == "__main__":
    asyncio.run(inspect_multikino())
