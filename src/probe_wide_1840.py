import httpx
import sys
import io

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    target_date = "2026-03-16"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    
    with httpx.Client(timeout=10) as client:
        # Range of typical IDs
        for cid in range(1060, 1120):
            url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
            try:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    films = {f['id']: f['name'] for f in data.get('body', {}).get('films', [])}
                    events = data.get('body', {}).get('events', [])
                    
                    found_1840 = False
                    for e in events:
                        time = e.get('eventDateTime').split('T')[1][:5]
                        if time == "18:40":
                            f_name = films.get(e['filmId'], "")
                            if "Bez wyj" in f_name:
                                found_1840 = True
                                break
                    
                    if found_1840:
                        # Try to get the cinema name from a different endpoint or just print the ID
                        print(f"ID {cid} has Bez wyjścia at 18:40")
                elif resp.status_code == 404:
                    pass
            except:
                pass

if __name__ == "__main__":
    main()
