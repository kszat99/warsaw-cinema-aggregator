import httpx
import sys
import io

def get_rep(cid):
    target_date = "2026-03-16"
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client() as client:
        try:
            resp = client.get(url, headers=headers)
            data = resp.json()
            events = data.get('body', {}).get('events', [])
            return sorted([e.get('eventDateTime') for e in events])
        except:
            return None

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    rep_1064 = get_rep("1064")
    rep_1071 = get_rep("1071")
    
    print(f"ID 1064: {len(rep_1064) if rep_1064 else 0} screenings")
    print(f"ID 1071: {len(rep_1071) if rep_1071 else 0} screenings")
    
    if rep_1064 == rep_1071 and rep_1064:
        print("IDENTICAL!")
    else:
        print("DIFFERENT!")

if __name__ == "__main__":
    main()
