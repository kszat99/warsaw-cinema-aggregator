"""Explicit pilot scope; no automatic enablement of other venues."""

import ssl

PROVIDERS = {"kinoteka": "kinoteka", "1074": "cinema_city"}
OFFSETS = {"kinoteka": (-5, 0, 5, 40), "cinema_city": (-5, 0, 5, 10)}
NAMES = {"kinoteka": "Kinoteka", "1074": "Cinema City Arkadia"}
RETRY_DELAY_MS = 30_000
# One 20s request for Kinoteka; three sequential 20s requests for Cinema City.
RETRY_BUDGET_MS = {"kinoteka": 20_000, "cinema_city": 60_000}


def cinema_name(cinema_id: str) -> str:
    return NAMES.get(cinema_id, cinema_id)


def transport_outcome(error: BaseException) -> str:
    """Do not retry TLS failures or log exception text containing request details."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return "tls_error"
        current = current.__cause__ or current.__context__
    return "network_error"
