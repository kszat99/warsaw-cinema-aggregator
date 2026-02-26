import asyncio
import sys
import io
from src.cinema_agg.build import PosterService
from src.cinema_agg.config import TMDB_API_KEY

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

async def test_poster():
    service = PosterService(TMDB_API_KEY)
    title = "Krzyżacy"
    norm = "krzyżacy"
    print(f"Fetching poster for: {title}")
    url = await service.get_poster(norm, title)
    print(f"Result URL: {url}")
    service.save_cache()

if __name__ == "__main__":
    asyncio.run(test_poster())
