import argparse
import asyncio
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cinema_agg.seat_availability import fetch_atlantic_seat_availability


async def main() -> None:
    parser = argparse.ArgumentParser(description="Read Atlantic seat availability for one screening")
    parser.add_argument("booking_url", help="Atlantic Default.aspx or OrderTickets.aspx event URL")
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="Screening date in YYYY-MM-DD form (defaults to today)",
    )
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as client:
        result = await fetch_atlantic_seat_availability(args.booking_url, args.date, client)

    output = asdict(result)
    output["checked_at"] = result.checked_at.isoformat()
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
