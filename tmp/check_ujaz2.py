import httpx
from bs4 import BeautifulSoup
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = httpx.get('https://u-jazdowski.pl/kino/repertuar', follow_redirects=True, verify=False)
soup = BeautifulSoup(r.text, 'lxml')
print(soup.title.text)

# Let's find any text that looks like a time hh:mm
import re
times = re.findall(r'\b(?:[01]\d|2[0-3]):[0-5]\d\b', r.text)
print("Times:", list(set(times))[:10])

# Let's find div classes
from collections import Counter
classes = [c for div in soup.find_all('div') for c in div.get('class', [])]
print(Counter(classes).most_common(20))
