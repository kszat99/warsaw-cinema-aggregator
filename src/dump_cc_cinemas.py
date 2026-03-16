import httpx
import json
import sys
import io

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    # This endpoint usually returns the list of all cinemas in the region
    url = "https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/cinemas?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.cinema-city.pl/'
    }
    with httpx.Client(timeout=20) as client:
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                with open("cinemas_dump.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                cinemas = data.get('body', {}).get('cinemas', [])
                print(f"Found {len(cinemas)} cinemas.")
                for c in cinemas:
                    # Filter for Warsaw or nearby
                    name = c.get('name')
                    # Look for Zielonka, Wołomin, Marki, Warszawa
                    if any(x in name for x in ["Zielonka", "Wołomin", "Marki", "Warszawa", "Łódź", "Arkadia", "Bemowo", "Mokotów"]):
                        print(f"ID: {c.get('id')} | Name: {name} | City: {c.get('cityName')}")
            else:
                print(f"Status: {resp.status_code}")
                # If blocked, try to print a bit of text
                print(resp.text[:500])
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
