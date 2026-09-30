"""Explicit pilot scope; no automatic enablement of other venues."""

PROVIDERS = {"kinoteka": "kinoteka", "1074": "cinema_city"}
OFFSETS = {"kinoteka": (-5, 0, 5, 40), "cinema_city": (-5, 0, 5, 10)}
NAMES = {"kinoteka": "Kinoteka", "1074": "Cinema City Arkadia"}


def cinema_name(cinema_id: str) -> str:
    return NAMES.get(cinema_id, cinema_id)
