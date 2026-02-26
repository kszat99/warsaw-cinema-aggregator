import asyncio
import httpx
import sys
import io
from src.cinema_agg.normalize import clean_title_for_search
from src.cinema_agg.config import TMDB_API_KEY

# Fix for Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def test_search():
    titles = [
        "Kornblumenblau",
        "Moon: Panda i ja",
        "Poranki: Kicia Kocia w podróży",
        "TAŃCZ ALBO GIŃ | Najlepsze z najgorszych",
        "Wielki błękit 4K (wersja kinowa)"
    ]
    
    api_key = TMDB_API_KEY
    
    async with httpx.AsyncClient() as client:
        for title in titles:
            clean = clean_title_for_search(title)
            print(f"\nRaw:   {title}")
            print(f"Clean: {clean}")
            
            params = {
                "api_key": api_key,
                "query": clean,
                "include_adult": "false",
                "page": 1,
                "language": "pl-PL"
            }
            r = await client.get("https://api.themoviedb.org/3/search/movie", params=params)
            results = r.json().get("results", [])
            
            if not results:
                print("  - No results in PL, trying global...")
                params.pop("language")
                r = await client.get("https://api.themoviedb.org/3/search/movie", params=params)
                results = r.json().get("results", [])
                
            if results:
                best = results[0]
                print(f"  - Found: {best.get('title')} ({best.get('release_date', '')[:4]})")
                print(f"  - Poster: {best.get('poster_path')}")
            else:
                print("  - STILL NO RESULTS")

if __name__ == "__main__":
    asyncio.run(test_search())
