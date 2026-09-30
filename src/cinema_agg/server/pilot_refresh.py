"""Linux-only refresh owner for the isolated Kinoteka/Arkadia pilot database."""

import asyncio
import importlib
import json
import signal
import sys
from datetime import datetime, timedelta

import httpx
from sqlalchemy import text

from .collector import WARSAW, collect, make_fetch, now_ms
from .database import database_engine, require_schema
from .settings import Settings


def main() -> None:
    if sys.platform == "win32":
        raise RuntimeError("The managed pilot refresh requires Linux.")
    fcntl = importlib.import_module("fcntl")
    path = Settings.from_environment().database_path
    # All pilot refreshes must use this entry point; raw collectors are not supported
    # against this isolated DB. flock is released by the OS even on SIGKILL/reboot.
    with path.with_suffix(".refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        engine = database_engine(path, readonly=False)
        try:
            with engine.begin() as connection:
                require_schema(connection)
                connection.execute(
                    text(
                        "UPDATE fetch_runs SET status='interrupted', "
                        "finished_at_ms=:now "
                        "WHERE status='running'"
                    ),
                    {"now": now_ms()},
                )
        finally:
            engine.dispose()

        def terminate(signum: int, frame: object) -> None:
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, terminate)

        async def refresh() -> dict[str, object]:
            today = datetime.now(WARSAW).date()
            async with httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pl-PL"},
            ) as client:
                return await collect(
                    path,
                    ["kinoteka", "1074", "wisla"],
                    [today, today + timedelta(days=1)],
                    make_fetch(client),
                )

        result = asyncio.run(refresh())
        print(json.dumps(result), flush=True)
        if result["status"] != "complete":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
