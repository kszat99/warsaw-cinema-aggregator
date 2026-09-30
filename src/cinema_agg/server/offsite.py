"""Encrypted offsite SQLite backup with verified restore before retention."""

import argparse
import hashlib
import importlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import httpx

from .database import database_engine, require_schema
from .offsite_b2 import B2

MAX_DATABASE = 128 * 1024**2
WARN_STORAGE = 1024**3
STOP_STORAGE = 2 * 1024**3
TAG = "cinema-pilot-v1"


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Backup integrity failure")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Backup foreign-key failure")
        counts = {
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("imports", "screenings", "seat_jobs", "seat_observations")
        }
    engine = database_engine(path, readonly=True)
    try:
        with engine.connect() as connection:
            require_schema(connection)
    finally:
        engine.dispose()
    return counts


def snapshot(source: Path, target: Path) -> dict[str, int]:
    if source.stat().st_size > MAX_DATABASE:
        raise ValueError("Database size requires budget review")
    with closing(
        sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    ) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    if target.stat().st_size > MAX_DATABASE:
        raise ValueError("Snapshot size requires budget review")
    return validate(target)


class Restic:
    def __init__(self, config: dict[str, str], repository: str, password: Path) -> None:
        # Do not inherit unrelated credentials or RESTIC_* overrides.
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/nonexistent",
            "RESTIC_REPOSITORY": repository,
            "RESTIC_PASSWORD_FILE": str(password),
            "AWS_ACCESS_KEY_ID": config["application_key_id"],
            "AWS_SECRET_ACCESS_KEY": config["application_key"],
        }

    def run(self, *args: str, output: BinaryIO | None = None) -> bytes:
        result = subprocess.run(
            [
                "/usr/bin/restic",
                "--no-cache",
                "--json",
                "-o",
                "s3.connections=2",
                *args,
            ],
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=output if output else subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
        if result.returncode:
            # stderr can include credentials/URLs: never expose it in exceptions.
            raise RuntimeError(f"Restic exit {result.returncode}")
        return result.stdout if output is None else b""


def save_status(path: Path, data: dict[str, Any]) -> None:
    fd, temp = tempfile.mkstemp(prefix=".offsite-status-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def backup_and_verify(
    source: Path, folder: Path, remote: B2, restic: Restic, state: dict[str, Any]
) -> None:
    remote.check_lifecycle()
    state["phase"] = "storage_budget"
    stored = remote.stored_bytes()
    state["stored_bytes"] = stored
    if stored + MAX_DATABASE * 2 >= STOP_STORAGE:
        raise ValueError("Offsite storage budget requires review")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage = folder / "cinema.sqlite3"
    restored = folder / "restored.sqlite3"
    try:
        state["phase"] = "snapshot"
        counts = snapshot(source, stage)
        original = digest(stage)
        state["phase"] = "upload"
        raw = restic.run("backup", "--host", "cinema-vps", "--tag", TAG, str(stage))
        summaries = [json.loads(line) for line in raw.splitlines() if line.strip()]
        latest = next(
            row for row in reversed(summaries) if row.get("message_type") == "summary"
        )
        snap = latest["snapshot_id"]
        if not re.fullmatch(r"[0-9a-f]{8,64}", snap):
            raise ValueError("Invalid snapshot identity")
        state.update(
            snapshot_id=snap, sha256=original, database_bytes=stage.stat().st_size
        )
        state["phase"] = "download_verify"
        with restored.open("wb") as handle:
            restic.run("dump", snap, str(stage), output=handle)
        if digest(restored) != original or validate(restored) != counts:
            raise ValueError("Offsite restore mismatch")
        state["restored_counts"] = counts
        state["phase"] = "repository_check"
        restic.run("check")
        # No deletion until the new snapshot round-trips and repository checks pass.
        state["phase"] = "retention"
        restic.run(
            "forget",
            "--tag",
            TAG,
            "--host",
            "cinema-vps",
            "--keep-daily",
            "7",
            "--keep-weekly",
            "4",
            "--prune",
        )
        state["stored_bytes"] = remote.stored_bytes()
        state.update(
            outcome="success",
            phase="complete",
            last_success_ms=now_ms(),
            storage_warning=state["stored_bytes"] >= WARN_STORAGE,
        )
    finally:
        # Exact local scratch files, never the live database or a retained backup.
        stage.unlink(missing_ok=True)
        restored.unlink(missing_ok=True)


def health(database: Path, now: int) -> dict[str, Any]:
    if not (database.parent / "offsite-enabled").exists():
        return {"status": "not_configured"}
    try:
        state = json.loads((database.parent / "offsite-status.json").read_text())
        state["status"] = "ok"
        if state["outcome"] == "running":
            # Starting a retry is not recovery; keep the incident until verified.
            if state.get("last_failure_ms", 0) > state.get("last_success_ms", 0):
                state["status"] = "failed"
            if now - state["started_ms"] > 20 * 60_000:
                state["status"] = "stuck"
        elif state["outcome"] != "success":
            state["status"] = "failed"
        if (
            not state.get("last_success_ms")
            or now - state["last_success_ms"] > 26 * 3600_000
        ):
            state["status"] = "stale"
        if state.get("storage_warning") and state["status"] == "ok":
            state["status"] = "storage_warning"
        return dict(state)
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "missing_or_invalid"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "run"))
    parser.add_argument(
        "--database", type=Path, default=Path("/var/lib/cinema-pilot/cinema.sqlite3")
    )
    parser.add_argument("--workdir", type=Path, default=Path("/var/lib/cinema-offsite"))
    args = parser.parse_args()
    os.umask(0o077)
    credentials = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/etc/warsaw-cinema"))
    status_path = args.database.parent / "offsite-status.json"
    state: dict[str, Any] = {}
    try:
        fcntl = importlib.import_module("fcntl")
        args.workdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (args.workdir / "run.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(json.dumps({"event": "offsite_already_running"}))
                return
            if status_path.exists():
                state = json.loads(status_path.read_text())
            state.pop("error_type", None)
            state.update(started_ms=now_ms(), outcome="running", phase="authentication")
            save_status(status_path, state)
            config = json.loads((credentials / "offsite-backup.json").read_text())
            password = credentials / "offsite-restic-password"
            if not password.is_file() or password.stat().st_size < 32:
                raise ValueError("Recovery password missing")
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                remote = B2(client, config)
                restic = Restic(config, remote.repository, password)
                if args.command == "init":
                    remote.check_lifecycle(configure=True)
                    restic.run("init")
                    state.update(outcome="initialized", phase="initialized")
                else:
                    backup_and_verify(
                        args.database, args.workdir, remote, restic, state
                    )
            state["finished_ms"] = now_ms()
            save_status(status_path, state)
            print(json.dumps({"event": "offsite_backup", **state}), flush=True)
    except Exception as error:
        state.update(
            outcome="failed",
            error_type=type(error).__name__,
            finished_ms=now_ms(),
            last_failure_ms=now_ms(),
        )
        save_status(status_path, state)
        print(
            json.dumps(
                {
                    "event": "offsite_failed",
                    "phase": state.get("phase"),
                    "error_type": type(error).__name__,
                }
            ),
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
