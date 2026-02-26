import re

with open('multikino_chunk_4687.js', encoding='utf-8') as f:
    content = f.read()

# Search for URL patterns that might be showtime API
patterns = [
    r'https?://[^\s"\'`]{10,150}',
    r'/api/[^\s"\'`]{5,100}',
    r'film[s]?[^\s"\'`]{0,50}session[s]?[^\s"\'`]{0,50}',
    r'showtime[s]?[^\s"\'`]{0,100}',
    r'schedule[^\s"\'`]{0,100}',
]

for pat in patterns:
    matches = re.findall(pat, content, re.IGNORECASE)
    if matches:
        print(f'\nPattern: {pat}')
        for m in matches[:5]:
            print(f'  {m}')

# Also look for fetch calls with URLs
fetch_patterns = re.findall(r'fetch\([^\)]{5,200}\)', content)
print(f'\nFetch calls ({len(fetch_patterns)} total):')
for m in fetch_patterns[:10]:
    print(f'  {m[:150]}')
