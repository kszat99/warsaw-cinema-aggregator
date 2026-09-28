"""Run with uv run --locked python -m cinema_agg.server."""

import sys

import uvicorn
from pydantic import ValidationError

from .app import create_app
from .logging import configure_logging
from .settings import Settings


def main() -> None:
    try:
        settings = Settings.from_environment()
    except ValidationError:
        # Do not print Pydantic input values or arbitrary environment variable names.
        print(
            "Invalid API configuration. Check CINEMA_API_HOST (127.0.0.1 or ::1), "
            "CINEMA_API_PORT (1024-65535), and remove unknown CINEMA_API_* variables.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    configure_logging()
    uvicorn.run(
        create_app(), host=settings.host, port=settings.port,
        access_log=False, log_config=None, proxy_headers=False,
        server_header=False, timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":
    main()
