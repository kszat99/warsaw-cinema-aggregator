import re

try:
    with open('multikino_full.html', encoding='utf-16-le', errors='replace') as f:
        content = f.read()
except Exception:
    with open('multikino_full.html', encoding='utf-8', errors='replace') as f:
        content = f.read()

print('File size:', len(content))

# Look for time patterns (HH:MM)
times = re.findall(r'\b\d{2}:\d{2}\b', content)
print('Time patterns found (first 20):', times[:20])

# Look for booking links
booking = re.findall(r'https?://[^\s"<>]{0,100}ticket[^\s"<>]{0,100}', content, re.IGNORECASE)
print('Booking links found (first 5):', booking[:5])

# Look for film/movie data
film_patterns = re.findall(r'"title"[:\s]+"[^"]{3,80}"', content)
print('Title patterns (first 10):', film_patterns[:10])

# Look for sessionId patterns
session_patterns = re.findall(r'sessionId[^"]{0,5}"[^"]{5,50}"', content)
print('Session patterns (first 5):', session_patterns[:5])

# Look for any JSON embedded
json_blocks = re.findall(r'\{[^{}]{200,500}\}', content[:100000])
print('Large JSON blocks found:', len(json_blocks))
if json_blocks:
    print('First block sample:', json_blocks[0][:200])
