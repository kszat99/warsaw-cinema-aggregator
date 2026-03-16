import httpx
import sys
import io

def check_cid(cid):
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client(follow_redirects=True, timeout=10) as client:
        try:
            resp = client.post(url, headers=headers) # Try POST to see if it hits the redirect logic
            resp = client.get(url, headers=headers)
            print(f"CID {cid} -> Final URL: {resp.url}")
            if "Zielonka" in resp.text: return "Zielonka"
            if "Manufaktura" in resp.text: return "Manufaktura"
            if "Mokotów" in resp.text: return "Mokotów"
            if "Wołomin" in resp.text: return "Wołomin"
            return "Unknown"
        except Exception as e:
            return f"Error: {e}"

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    for cid in ["1070", "1080", "1085"]:
        name = check_cid(cid)
        print(f"ID {cid}: {name}")

if __name__ == "__main__":
    main()
