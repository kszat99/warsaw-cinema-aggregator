import httpx
import sys
import io

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cid = "1080"
    target_date = "2026-03-16"
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client(follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            events = data.get('body', {}).get('events', [])
            if events:
                print(f"Found {len(events)} events for CID {cid}")
                sample_event = events[0]
                booking_link = sample_event.get('bookingLink')
                print(f"Sample booking link: {booking_link}")
                
                if booking_link:
                    resp_redirect = client.get(booking_link, headers=headers)
                    print(f"Final redirect URL: {resp_redirect.url}")
                    # Look for cinema name in HTML
                    if "Manufaktura" in resp_redirect.text:
                        print("Confirmed: Redirects to Manufaktura (Łódź)")
                    if "Zielonka" in resp_redirect.text:
                        print("Redirects to Zielonka")
            else:
                print("No events found for this ID today.")
        else:
            print(f"Error fetching data: {resp.status_code}")

if __name__ == "__main__":
    main()
