"""Explicit operator commands: migrate, then import-json. No cinema traffic."""

import argparse
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .database import SchemaUnavailable, migrate
from .importer import import_snapshot
from .settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, help="Override CINEMA_API_DATABASE_PATH"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Create/upgrade the local SQLite schema")
    importer = commands.add_parser(
        "import-json", help="Import a validated legacy snapshot"
    )
    importer.add_argument("source", type=Path)
    importer.add_argument(
        "--source-timezone",
        required=True,
        help="IANA zone for naive source timestamps, e.g. Europe/Warsaw or UTC",
    )
    args = parser.parse_args()
    try:
        path = args.database or Settings.from_environment().database_path
        if args.command == "migrate":
            migrate(path)
            result: dict[str, object] = {"status": "schema_ready"}
        else:
            result = import_snapshot(path, args.source, args.source_timezone)
    except ValidationError as exc:
        print(
            f"Validation failed: {exc.error_count()} issue(s). "
            "Check source field types, "
            "nonempty screenings, HTTP(S) links and configuration. "
            "No snapshot was committed; input values are omitted.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except (
        CommandError,
        OSError,
        ValueError,
        SQLAlchemyError,
        SchemaUnavailable,
        ZoneInfoNotFoundError,
    ):
        print(
            "Database operation failed. Check configuration/path permissions, "
            "run migrate first, and validate the source fields/timezone. "
            "Imports must be nonempty, unambiguous "
            "and newer than the current snapshot (identical reimports are safe).",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
