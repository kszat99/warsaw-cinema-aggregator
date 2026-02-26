import httpx
import json
import re

url = "https://www.multikino.pl/filmy/piepzyc-mickiewicza-3"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

resp = httpx.get(url, headers=headers, follow_redirects=True)
html = resp.text

match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
if match:
    data = json.loads(match.group(1))
    film_id = data["pageProps"]["layoutData"]["sitecore"]["context"]["film"]["filmId"]["value"]
    print(f"Film ID: {film_id}")
    
    # Let's search if the showings are in the HTML directly now that we're on the film's page
    def find_showings(d, path=""):
        if isinstance(d, dict):
            if "showings" in d:
                print(f"FOUND showings at {path}! Items: {len(d['showings'])}")
            for k, v in d.items():
                find_showings(v, f"{path}.{k}" if path else k)
        elif isinstance(d, list):
            for i, v in enumerate(d):
                find_showings(v, f"{path}[{i}]")
                
    find_showings(data)
    
    # Since they aren't here, see the script tag
    build_id = data["buildId"]
    print(f"Build ID: {build_id}")
    
    api_url = f"https://www.multikino.pl/_next/data/{build_id}/pl/filmy/piepzyc-mickiewicza-3.json"
    print(f"To get JSON data for this film: {api_url}")
else:
    print("No __NEXT_DATA__")
