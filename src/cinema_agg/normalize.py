import html
import re
import unicodedata
from typing import List, Tuple

ROMAN_NUMERALS = {
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}

TITLE_PREFIXES_TO_DROP = [
    "gwiezdne wojny",
]


def normalize_title(title: str) -> str:
    """Normalize titles for grouping/deduplication."""
    if not title:
        return ""

    title = clean_title_for_search(html.unescape(title))
    title = title.lower().strip()
    title = unicodedata.normalize("NFKD", title)
    title = "".join(ch for ch in title if not unicodedata.combining(ch))

    title = re.sub(r"\s*&\s*", " i ", title)
    title = re.sub(r"\band\b", "i", title)
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()

    for prefix in TITLE_PREFIXES_TO_DROP:
        if title.startswith(prefix + " "):
            title = title[len(prefix):].strip()

    title = re.sub(
        r"\b(ii|iii|iv|v|vi|vii|viii|ix|x)\b",
        lambda match: ROMAN_NUMERALS[match.group(1)],
        title,
    )

    return title.strip()


def clean_title_for_search(title: str) -> str:
    """Strip promotional garbage while keeping a human-readable movie title."""
    if not title:
        return ""

    title = html.unescape(title)
    has_ukrainian_marker = bool(re.search(r"ukrai|\u0443\u043a\u0440\u0430", title, flags=re.IGNORECASE))

    title = re.sub(r"\[.*?\]", "", title)
    title = re.sub(r"\(.*?\)", "", title)

    prefixes = ["poranki", "maraton", "dkf", "kino seniora", "seans", "przedpremiera", "pokaz"]
    for prefix in prefixes:
        title = re.sub(f"^{prefix}\\s*:\\s*", "", title, flags=re.IGNORECASE)

    quotes_open = "\u201e\u201c\u00ab\u0022"
    quotes_close = "\u201d\u201f\u00bb\u0022"
    quoted_search = re.search(f"[{quotes_open}]([^{quotes_close}]+)[{quotes_close}]", title)
    if quoted_search:
        title = quoted_search.group(1)

    title = re.sub(r"\s*[|\u2013].*$", "", title)
    title = re.sub(r"\s+-\s+.*$", "", title)

    if has_ukrainian_marker and not re.search(r"ukrai|\u0443\u043a\u0440\u0430", title, flags=re.IGNORECASE):
        title = f"{title} ukrainski"

    garbage_patterns = [
        r"\s*dubbing\s*$",
        r"\s*napisy\s*$",
        r"\s*lektor\s*$",
        r"\s*wersja.*\s*$",
        r"\s*\bua\b\s*$",
        r"\s*\ben\b\s*$",
        r"\s*\bpl\b\b\s*$",
        r"\s*\bdub\b\s*$",
        r"\s*\bnap\b\s*$",
        r"\s*4k\s*$",
        r"\s*2d\s*$",
        r"\s*3d\s*$",
        r"\s*imax\s*$",
        r"\s*w helios na scenie\s*$",
    ]
    for pattern in garbage_patterns:
        title = re.sub(pattern, "", title, flags=re.IGNORECASE)

    title = re.sub(r"[*:]", " ", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def clean_title_search_candidates(title: str) -> List[str]:
    """Return best-effort poster search candidates from noisy event titles."""
    if not title:
        return []

    original = html.unescape(title).strip()
    candidates = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", " ", value).strip(" -:|")
        if value and value not in candidates:
            candidates.append(value)

    without_years = re.sub(r"\(\s*(19|20)\d{2}\s*\)", "", original)
    without_brackets = re.sub(r"\[.*?\]", "", without_years)

    event_prefix_patterns = [
        r"^kino letnie\s*\d{4}\s*:\s*",
        r"^lato w mieście\s*\d{4}\s*:\s*",
        r"^lato w miescie\s*\d{4}\s*:\s*",
        r"^lot kino letnie\s*:\s*",
        r"^wsp\s*:\s*",
        r"^wajda\s*:\s*re-wizje\s*:\s*",
        r"^pora dla seniora\s*:\s*",
        r"^kultowe klasyki\s*:\s*",
        r"^filmowe poranki\s*:\s*",
        r"^maraton\s*:\s*",
        r"^dkf\s*:\s*",
        r"^kino seniora\s*:\s*",
        r"^seans\s*:\s*",
        r"^przedpremiera\s*:\s*",
        r"^pokaz\s*:\s*",
    ]

    stripped = without_brackets
    for pattern in event_prefix_patterns:
        stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)

    add(stripped)
    add(clean_title_for_search(stripped))

    # Keep the subtitle for known title forms like "Rambo - pierwsza krew".
    if " - " in stripped:
        add(stripped)
        add(re.sub(r"\s+-\s+(napisy|dubbing|lektor|przedpremiera).*$", "", stripped, flags=re.IGNORECASE))

    # Sometimes cinemas add useful English titles after a slash.
    for part in re.split(r"\s*/\s*", stripped):
        add(part)
        add(clean_title_for_search(part))

    return candidates


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

    if "ukrai" in combined or "\u0443\u043a\u0440\u0430" in combined or " ua" in combined:
        language = "ua"
    elif "napisy" in combined or " nap" in combined or "nap." in combined:
        language = "nap"
    elif "dubbing" in combined or " dub" in combined or "dub." in combined:
        language = "dub"
    elif "lektor" in combined or " vo" in combined:
        language = "voiceover"

    return language, tags
