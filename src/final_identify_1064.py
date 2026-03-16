import httpx
import sys
import io

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cid = "1064"
    target_date = "2026-03-16"
    url = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/10103/film-events/in-cinema/{cid}/at-date/{target_date}?attr=&lang=pl_PL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client() as client:
        resp = client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            events = data.get('body', {}).get('events', [])
            if events:
                # Try to get the booking link and see where it goes
                booking_url = events[0].get('bookingLink')
                print(f"ID 1064 booking link: {booking_url}")
                
                resp_booking = client.get(booking_url, headers=headers, follow_redirects=True)
                text = resp_booking.text
                if "Północna" in text: print("Found Północna in booking page!")
                if "Białołęka" in text: print("Found Białołęka in booking page!")
                if "Manufaktura" in text: print("Found Manufaktura in booking page!")
            else:
                print("No events for 1064 today.")
        else:
            print(f"Error {resp.status_code}")

if __name__ == "__main__":
    main()
