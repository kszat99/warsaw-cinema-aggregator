import httpx
import re
import json

url = "https://multikino.pl/repertuar/warszawa-mlociny/teraz-gramy"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
}

resp = httpx.get(url, headers=headers, follow_redirects=True)
html = resp.text

print(f"Status: {resp.status_code}")
print(f"Size: {len(html)}")

# Find next_data
match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
if match:
    # Save the chunk to a file
    with open("multikino_live_nextdata.json", "w", encoding="utf-8") as f:
        f.write(match.group(1))
    print(f"Saved __NEXT_DATA__ ({len(match.group(1))} chars)")
    
    # Check if this live version has "sessionId" or "showings"
    if "sessionId" in match.group(1):
        print("Live data HAS sessionId!")
        
        # Check if showings are in it
        data = json.loads(match.group(1))
        # Look for showings
        
        # let's just dump all showings
        def find_showings(d, path=""):
            if isinstance(d, dict):
                if "showings" in d and isinstance(d["showings"], list) and len(d["showings"]) > 0:
                    print(f"FOUND showings at {path}")
                    print(f"Sample showing: {d['showings'][0]}")
                    return True
                for k, v in d.items():
                    if find_showings(v, f"{path}.{k}" if path else k):
                        return True
            elif isinstance(d, list):
                for i, v in enumerate(d):
                    if find_showings(v, f"{path}[{i}]"):
                        return True
            return False
        
        find_showings(data)
    else:
        print("Live data DOES NOT have sessionId.")

else:
    print("No __NEXT_DATA__ found")
