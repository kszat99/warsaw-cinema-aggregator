import httpx
import sys
import io

def get_repertoire(cid):
    target_date = "2026-03-16"
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client() as client:
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                films = {f['id']: f['name'] for f in data.get('body', {}).get('films', [])}
                events = data.get('body', {}).get('events', [])
                # Return a summary: set of (film_name, time)
                return sorted([(films.get(e['filmId']), e.get('eventDateTime').split('T')[1][:5]) for e in events])
            return None
        except:
            return None

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    rep_1080 = get_repertoire("1080")
    rep_1085 = get_repertoire("1085")
    
    print(f"ID 1080: Found {len(rep_1080) if rep_1080 else 0} screenings")
    print(f"ID 1085: Found {len(rep_1085) if rep_1085 else 0} screenings")
    
    # Common films and times?
    if rep_1080 and rep_1085:
        set_1080 = set(rep_1080)
        set_1085 = set(rep_1085)
        common = set_1080.intersection(set_1085)
        print(f"Common screenings: {len(common)}")
        
        print("\nUnique to 1080 (first 5):")
        for x in sorted(list(set_1080 - set_1085))[:5]:
            print(f"  {x}")
            
        print("\nUnique to 1085 (first 5):")
        for x in sorted(list(set_1085 - set_1080))[:5]:
            print(f"  {x}")
            
if __name__ == "__main__":
    main()
