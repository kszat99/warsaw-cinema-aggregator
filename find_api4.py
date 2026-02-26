import re

with open('multikino_chunk_4687.js', encoding='utf-8') as f:
    content = f.read()

# Find WP function definition
positions = [m.start() for m in re.finditer(r'WP\b', content)]
print(f'Found {len(positions)} WP occurrences')

# Look for WP definition
wp_defs = re.findall(r'WP[=:][^;,\}]{0,200}', content)
print('\nWP definitions:')
for d in wp_defs[:10]:
    print(f'  {d[:150]}')

# Look for the showtime/session endpoint
session_patterns = [
    r'session[s]?[/\?][^\s"\'`]{0,100}',
    r'showtime[s]?[/\?][^\s"\'`]{0,100}',
    r'schedule[/\?][^\s"\'`]{0,100}',
    r'repertoire[/\?][^\s"\'`]{0,100}',
    r'film[s]?/[^\s"\'`]{0,100}date[^\s"\'`]{0,100}',
]

for pat in session_patterns:
    matches = re.findall(pat, content, re.IGNORECASE)
    if matches:
        print(f'\nPattern: {pat}')
        for m in matches[:3]:
            print(f'  {m[:150]}')
