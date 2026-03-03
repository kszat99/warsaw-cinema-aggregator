import re
from typing import Tuple, List

def normalize_title(title: str) -> str:
    """Advanced normalization: strip promo suffixes, lowercase, remove punctuation for deduplication."""
    if not title:
        return ""
    
    # 1. Clean from promotional garbage first
    title = clean_title_for_search(title)
    
    # 2. Lowercase and strip
    title = title.lower().strip()
    
    # 3. Remove all non-alphanumeric characters (keep local characters)
    # This ensures "Father, Mother" and "Father Mother" are identical
    title = re.sub(r'[^\w\s]', '', title)
    
    # 4. Standardize whitespace
    title = re.sub(r'\s+', ' ', title)
    
    return title.strip()

def clean_title_for_search(title: str) -> str:
    """Strips promotional garbage but keeps the 'clean' human-readable title."""
    if not title:
        return ""

    # 1. Remove common bracketed/parentheses tags first
    title = re.sub(r'\[.*?\]', '', title)
    title = re.sub(r'\(.*?\)', '', title)
    
    # 2. Strip common prefixes like "Poranki:", "Maraton:", "Przedpremierowy pokaz:"
    # This keeps only what's after the first colon if it looks like a prefix
    prefixes = ["poranki", "maraton", "dkf", "kino seniora", "seans", "przedpremiera", "pokaz"]
    for p in prefixes:
        title = re.sub(f'^{p}\\s*:\\s*', '', title, flags=re.IGNORECASE)

    # 2b. Extract quoted title if present (Polish „..." or "..." quotation marks)
    # Handles: „Bez wyjścia" pokaz przedpremierowy w ramach cyklu Spotkania Filozoficzne
    # U+201E „  U+201C "  U+00AB «  (opening)
    # U+201D "  U+201F ‟  U+00BB »  (closing)
    # NOTE: non-raw string so \u escapes are interpreted as Unicode characters
    # More flexible regex: match quoted part, then optionally anything else
    quoted_match = re.match('[\u201e\u201c\u00ab](.+?)[\u201d\u201f\u00bb](.*)', title)
    if quoted_match:
        title = quoted_match.group(1)

    # 3. Strip promotional suffixes after separators
    # We only strip if it's ONE of these: |, –, or a dash surrounded by spaces
    title = re.sub(r'\s*[|–].*$', '', title)
    title = re.sub(r'\s+-\s+.*$', '', title)
    
    # 4. Remove common trailing garbage words and technical tags
    garbage_patterns = [
        r'\s*dubbing\s*$',
        r'\s*napisy\s*$',
        r'\s*lektor\s*$',
        r'\s*wersja.*\s*$',
        r'\s*ua\s*$',
        r'\s*en\s*$',
        r'\s*pl\s*$',
        r'\s*dub\s*$',
        r'\s*nap\s*$',
        r'\s*4k\s*$',
        r'\s*2d\s*$',
        r'\s*3d\s*$',
        r'\s*imax\s*$',
    ]
    for pattern in garbage_patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)

    # 5. Remove punctuation for search (TMDB handles well, but let's be clean)
    title = re.sub(r'[*:]', ' ', title)
    
    title = re.sub(r'\s+', ' ', title)
    return title.strip()

def extract_language_and_tags(title_raw: str, format_raw: str = "") -> Tuple[str, List[str]]:
    """
    Extract language (nap/dub/voiceover/org/ua) and tags (3D, etc.) 
    from raw title or format strings.
    """
    tags = []
    language = "org"
    
    combined = (title_raw + " " + format_raw).lower()
    
    if "3d" in combined:
        tags.append("3D")
    
    if "ukraiński" in combined or "ua" in combined:
        language = "ua"
    elif "napisy" in combined or " nap" in combined or "nap." in combined:
        language = "nap"
    elif "dubbing" in combined or " dub" in combined or "dub." in combined:
        language = "dub"
    elif "lektor" in combined or " vo" in combined:
        language = "voiceover"
        
    return language, tags
