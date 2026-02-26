import re

with open('multikino_chunk_4687.js', encoding='utf-8') as f:
    content = f.read()

print('File size:', len(content))

# Find cinemaId occurrences with context
positions = [m.start() for m in re.finditer('cinemaId', content, re.IGNORECASE)]
print(f'Found {len(positions)} cinemaId occurrences')

for pos in positions[:5]:
    start = max(0, pos - 200)
    end = min(len(content), pos + 300)
    print(f'\n--- Position {pos} ---')
    print(content[start:end])
    print()
