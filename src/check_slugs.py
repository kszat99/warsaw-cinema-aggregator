import httpx
import sys
import io

def check_slug(slug):
    url = f"https://www.cinema-city.pl/kinos/{slug}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client(follow_redirects=True) as client:
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                if "/kinos/" + slug in resp.url.path:
                    # Look for ID in script or page
                    text = resp.text
                    # Often found in "cinemaId": "1234"
                    import re
                    match = re.search(r'cinemaId["\']:\s*["\'](\d+)["\']', text)
                    if match:
                        return f"Found! ID: {match.group(1)}"
                    return "Found, but ID not in text"
            return f"Status {resp.status_code} at {resp.url}"
        except Exception as e:
            return f"Error: {e}"

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    slugs = ["zielonka", "wolomin", "marki", "białołęka", "bemowo", "arkadia", "galeria-północna", "galeria-mokotów", "sadyba", "janki", "promenada", "manufaktura", "zielona-gora"]
    for slug in slugs:
        res = check_slug(slug)
        print(f"Slug '{slug}': {res}")

if __name__ == "__main__":
    main()
