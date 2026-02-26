import re

with open('multikino_chunk_4687.js', encoding='utf-8') as f:
    content = f.read()

# Find /api/films with context
positions = [m.start() for m in re.finditer(r'/api/films', content, re.IGNORECASE)]
print(f'Found {len(positions)} /api/films occurrences')

for pos in positions[:5]:
    start = max(0, pos - 300)
    end = min(len(content), pos + 300)
    print(f'\n--- Position {pos} ---')
    print(content[start:end])
    print()

# Also look for /api/articles context
positions2 = [m.start() for m in re.finditer(r'/api/articles', content, re.IGNORECASE)]
print(f'\nFound {len(positions2)} /api/articles occurrences')
for pos in positions2[:2]:
    start = max(0, pos - 200)
    end = min(len(content), pos + 200)
    print(f'\n--- Position {pos} ---')
    print(content[start:end])
