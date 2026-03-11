import httpx
import re
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = httpx.get('https://www.kinokultura.pl/repertuar/', follow_redirects=True)

# Find rep_movie function
match = re.search(r'function\s+rep_movie.*?(?=\n\n|\Z)', r.text, re.DOTALL)
if match:
    print(match.group(0)[:1500])
else:
    # See what url calls are made
    print("AJAX calls:")
    ajax = re.findall(r'(\.ajax|\$\.post|\$\.get).*?url.*?[\'"]([^\'"]+)[\'"]', r.text, re.I | re.DOTALL)
    for a in ajax:
        print(a)
