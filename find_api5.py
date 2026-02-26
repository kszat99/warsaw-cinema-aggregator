import re

with open('multikino_chunk_7953.js', encoding='utf-8') as f:
    content = f.read()

print('File size:', len(content))

# Search for DataManager patterns
dm_patterns = re.findall(r'baseUrl[^\n]{0,200}', content)
print('\nbaseUrl patterns:')
for d in dm_patterns[:10]:
    print(f'  {d[:200]}')

# Search for session/showtime endpoints
session_patterns = [
    r'session[s]?[^\s"\'`]{0,100}',
    r'showtime[s]?[^\s"\'`]{0,100}',
    r'schedule[^\s"\'`]{0,100}',
    r'/api/[^\s"\'`]{5,100}',
]

for pat in session_patterns:
    matches = re.findall(pat, content, re.IGNORECASE)
    if matches:
        print(f'\nPattern: {pat}')
        for m in matches[:5]:
            print(f'  {m[:150]}')
