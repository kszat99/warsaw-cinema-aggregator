import httpx
from bs4 import BeautifulSoup
import sys
import io

def get_name(cid):
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client(follow_redirects=True, timeout=10) as client:
        try:
            resp = client.get(url, headers=headers)
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Look for the cinema name. It's often in a <span> or <h1> or specifically marked.
            # Let's see what's in the title
            title = soup.title.string if soup.title else "No Title"
            return title
        except Exception as e:
            return f"Error: {e}"

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    for cid in ["1074", "1070", "1080", "1085", "1090"]:
        name = get_name(cid)
        print(f"ID {cid} -> Title: {name}")

if __name__ == "__main__":
    main()
