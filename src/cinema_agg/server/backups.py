"""Validated backups with managed retention; manual copies are protected."""

import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .settings import Settings

MANAGED = re.compile(r"managed-backup-(\d{8}T\d{12})\.sqlite3$")


def candidates(folder: Path) -> list[Path]:
    return [
        p
        for p in folder.glob("*.sqlite3")
        if not p.is_symlink()
        and p.is_file()
        and p.name.startswith(("backup-", "managed-backup-"))
    ]


def retention(folder: Path) -> tuple[list[Path], list[Path]]:
    managed = []
    for path in candidates(folder):
        match = MANAGED.fullmatch(path.name)
        if match:
            try:
                stamp = datetime.strptime(match[1], "%Y%m%dT%H%M%S%f")
            except ValueError:
                continue
            managed.append((stamp, path))
    managed.sort(reverse=True)
    keep: list[Path] = []
    days: set[str] = set()
    weeks: set[tuple[int, int]] = set()
    for stamp, path in managed:
        day = stamp.date().isoformat()
        if day not in days and len(days) < 7:
            days.add(day)
            keep.append(path)
    oldest_day = min(days) if days else ""
    for stamp, path in managed:
        week = (stamp.isocalendar().year, stamp.isocalendar().week)
        if (
            stamp.date().isoformat() < oldest_day
            and week not in weeks
            and len(weeks) < 4
        ):
            weeks.add(week)
            keep.append(path)
    return keep, [p for _, p in managed if p not in keep]


def backup(database: Path, folder: Path) -> dict[str, object]:
    folder.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("managed-backup-%Y%m%dT%H%M%S%f.sqlite3")
    target = folder / name
    temporary = folder / (name + ".partial")
    # Exclusive reservation prevents overwriting another run's temporary file.
    with temporary.open("xb"):
        pass
    try:
        with closing(
            sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        ) as src:
            with closing(sqlite3.connect(temporary)) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("Backup validation failed")
                dst.execute("SELECT id FROM seat_observations LIMIT 0")
        temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)
    keep, remove = retention(folder)
    for old in remove:
        old.unlink()  # Exact managed filenames only, after a new valid copy exists.
    return {
        "backup": target.name,
        "retained_managed": len(keep),
        "pruned_managed": len(remove),
        "bytes": target.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    path = args.database or Settings.from_environment().database_path
    print(json.dumps(backup(path, path.parent / "backups")))


if __name__ == "__main__":
    main()
