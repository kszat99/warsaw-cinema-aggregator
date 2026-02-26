import asyncio
from datetime import date
from src.cinema_agg.adapters.kinoteka import KinotekaAdapter
import json

async def test():
    adapter = KinotekaAdapter("kinoteka", "Kinoteka", "https://kinoteka.pl/repertuar/")
    print("Fetching Kinoteka for today...")
    screenings = await adapter.fetch_screenings(date.today())
    print(f"Found {len(screenings)} screenings")
    for s in screenings[:5]:
        print(f"Movie: {s.title_raw}, Duration: {s.duration_min}")
    
    if screenings:
        with open("test_kinoteka.json", "w", encoding="utf-8") as f:
            f.write(json.dumps([s.model_dump(mode='json') for s in screenings], indent=2))

if __name__ == "__main__":
    asyncio.run(test())
