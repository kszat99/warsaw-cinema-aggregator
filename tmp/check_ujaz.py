import httpx
from bs4 import BeautifulSoup
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = httpx.get('https://u-jazdowski.pl/kino/repertuar', follow_redirects=True, verify=False)
soup = BeautifulSoup(r.text, 'lxml')

movies = soup.find_all(class_=lambda c: c and ('movie' in c or 'film' in c or 'repert' in c))
print(f"Found {len(movies)} elements looking like movies")

links = [a['href'] for a in soup.find_all('a', href=True) if 'bilet' in a['href'] or 'ticket' in a['href'] or 'rezerwacja' in a['href']]
print(f"Found ticket links: {list(set(links))[:5]}")
