import httpx
from bs4 import BeautifulSoup
import re
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = httpx.get('https://www.kinokultura.pl/repertuar/', follow_redirects=True)
soup = BeautifulSoup(r.text, 'lxml')

scripts = soup.find_all('script', src=True)
print("Scripts:")
for s in scripts:
    print(s['src'])
