import httpx
import sys
import io

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

r = httpx.get('https://www.kinokultura.pl/_core/_js/index_01.js', follow_redirects=True)
import re

match = re.search(r'function\s+rep_movie.*?\{.*?(?=\n\s*function|\Z)', r.text, re.DOTALL)
if match:
    print(match.group(0)[:1000])

ajaxes = re.findall(r'\$\.ajax.*?url:\s*[\'"]([^\'"]+)[\'"]', r.text, re.DOTALL)
print("AJAX calls in JS:", set(ajaxes))
