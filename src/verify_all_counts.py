import httpx
import sys
import io

def get_count(cid):
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
                events = data.get('body', {}).get('events', [])
                return len(events)
            return f"Error {resp.status_code}"
        except Exception as e:
            return f"Ex: {e}"

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    ids = ["1060", "1061", "1064", "1068", "1069", "1070", "1071", "1074"]
    for cid in ids:
        count = get_count(cid)
        print(f"ID {cid}: {count} screenings")

if __name__ == "__main__":
    main()
