import httpx
from bs4 import BeautifulSoup
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = httpx.get('https://www.kinokultura.pl/repertuar/', follow_redirects=True)
soup = BeautifulSoup(r.text, 'lxml')

reps = soup.find_all('div', class_=lambda c: c and 'content_rep' in c)
for rep in reps[:3]:
    print(rep.prettify()[:1000])

print("="*40)
hours = soup.find_all('div', id=lambda x: x and x.startswith('f_r21'))
for h in hours[:3]:
    print(h.prettify()[:500])
