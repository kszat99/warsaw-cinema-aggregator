import httpx
import sys
import io

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    target_date = "2026-03-16"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.cinema-city.pl/'
    }
    
    # Range of IDs to check
    # Many are in 1060-1090, but let's check more
    found_any = False
    with httpx.Client(timeout=10) as client:
        # Check IDs from 1060 to 1110
        for cid in range(1060, 1110):
            url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
            try:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    body = data.get('body', {})
                    films = {f['id']: f['name'] for f in body.get('films', [])}
                    events = body.get('events', [])
                    
                    for e in events:
                        time = e.get('eventDateTime').split('T')[1][:5]
                        if time == "18:40":
                            f_id = e.get('filmId')
                            f_name = films.get(f_id, "Unknown")
                            if "Bez wyj" in f_name:
                                print(f"MATCH FOUND: CID {cid} has 'Bez wyjścia' at 18:40")
                                found_any = True
            except:
                pass
    
    if not found_any:
        print("No matches found in range 1060-1110.")

if __name__ == "__main__":
    main()
