import httpx
from bs4 import BeautifulSoup
import sys
import io

def get_name(cid):
    url = f"https://www.cinema-city.pl/pl/buy-tickets-by-cinema?in-cinema={cid}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    with httpx.Client(follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        # Look for the selected cinema in the dropdown or header
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Check for <option selected="selected" value="1085">Name</option>
        selected = soup.find('option', selected=True)
        if selected:
            return f"OPT: {selected.text.strip()} (ID: {selected.get('value')})"
            
        # Check for a specific breadcrumb or header
        h1 = soup.find('h1')
        if h1:
            return f"H1: {h1.text.strip()}"
            
        return "Not found"

def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    for cid in ["1070", "1080", "1085", "1071", "1064", "1069"]:
        print(f"ID {cid}: {get_name(cid)}")

if __name__ == "__main__":
    main()
