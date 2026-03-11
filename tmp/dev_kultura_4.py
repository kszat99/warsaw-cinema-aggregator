import httpx
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = httpx.get('https://www.kinokultura.pl/repertuar/', follow_redirects=True)
for chunk in r.text.split('function'):
    if 'rep_movie' in chunk:
        print(chunk[:1000])
        break
