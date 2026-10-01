"""Explicit pilot scope; no automatic enablement of other venues."""

import ssl

CITY_CINEMAS = {
    "1074": "Cinema City Arkadia",
    "1061": "Cinema City Bemowo",
    "1060": "Cinema City Sadyba (only IMAX)",
    "1070": "Cinema City Galeria Mokotów",
    "1068": "Cinema City Promenada",
    "1096": "Cinema City Galeria Północna (Białołęka)",
    "1069": "Cinema City Janki",
}
PROVIDERS = {
    "kinoteka": "kinoteka",
    "wisla": "msi_wisla",
    "atlantic": "msi_atlantic",
    **dict.fromkeys(CITY_CINEMAS, "cinema_city"),
}
HISTORY_OFFSETS = (-1440, -720, -360, -180, -120, -60, -30, -15)
OFFSETS = {
    "kinoteka": (*HISTORY_OFFSETS, -5, 0, 5, 40),
    "cinema_city": (*HISTORY_OFFSETS, -5, 0, 5, 10),
    "msi_wisla": (*HISTORY_OFFSETS, -5, -2, 0, 5),
    "msi_atlantic": (*HISTORY_OFFSETS, -5, 0, 5),
}
NAMES = {
    "kinoteka": "Kinoteka",
    **CITY_CINEMAS,
    "wisla": "Novekino Wisła",
    "atlantic": "Novekino Atlantic",
}
RETRY_DELAY_MS = 30_000
# Kinoteka/City reserve their request budgets. Wisla's 120s reserve prevents
# immediate retries inside the 120s job window during this initial session pilot.
RETRY_BUDGET_MS = {
    "kinoteka": 20_000,
    "cinema_city": 60_000,
    "msi_wisla": 120_000,
    "msi_atlantic": 120_000,
}


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


DISPATCH_GROUPS = {
    "cinema_city": ("cinema_city",),
    "kinoteka": ("kinoteka",),
    "novekino": ("msi_wisla", "msi_atlantic"),
}
PROVIDER_SPACING_MS = 5000
