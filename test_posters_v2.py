import asyncio
import sys
import io
from src.cinema_agg.build import PosterService
from src.cinema_agg.config import TMDB_API_KEY
from src.cinema_agg.normalize import normalize_title

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def test_posters():
    service = PosterService(TMDB_API_KEY)
    test_titles = [
        "Bez wyjścia [seans przedpremierowy]",
        "Bugonia | Nowy film Yorgosa Lanthimosa",
        "Hamnet",
        "Kopnęłabym cię, gdybym mogła",
        "Krzyżacy"
    ]
    
    print("Testing improved poster matching:")
    for title_raw in test_titles:
        norm = normalize_title(title_raw)
        url = await service.get_poster(norm, title_raw)
        print(f"  - Title: '{title_raw}'")
        print(f"    Norm:  '{norm}'")
        print(f"    URL:   {url}")
    
    # Do NOT save cache here to avoid polluting final build if it fails
    # service.save_cache()

if __name__ == "__main__":
    asyncio.run(test_posters())
