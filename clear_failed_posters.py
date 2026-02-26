import json
from pathlib import Path

cache_path = Path("dist/poster_cache.json")
if cache_path.exists():
    with open(cache_path, "r", encoding="utf-8") as f:
        cache = json.load(f)
    
    initial_count = len(cache)
    # Remove null values to force re-fetch with new logic
    cache = {k: v for k, v in cache.items() if v is not None}
    removed = initial_count - len(cache)
    
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    
    print(f"Cleared {removed} null entries from poster cache. Total now: {len(cache)}")
else:
    print("No poster cache found.")
