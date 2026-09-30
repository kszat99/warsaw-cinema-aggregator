"""Explicit pilot scope; no automatic enablement of other venues."""

import ssl

PROVIDERS = {"kinoteka": "kinoteka", "1074": "cinema_city", "wisla": "msi_wisla"}
OFFSETS = {
    "kinoteka": (-5, 0, 5, 40),
    "cinema_city": (-5, 0, 5, 10),
    "msi_wisla": (-5, 0, 5),
}
NAMES = {
    "kinoteka": "Kinoteka",
    "1074": "Cinema City Arkadia",
    "wisla": "Novekino Wisła",
}
RETRY_DELAY_MS = 30_000
# Kinoteka/City reserve their request budgets. Wisla's 120s reserve prevents
# immediate retries inside the 120s job window during this initial session pilot.
RETRY_BUDGET_MS = {"kinoteka": 20_000, "cinema_city": 60_000, "msi_wisla": 120_000}


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
