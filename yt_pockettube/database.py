"""SQLite bootstrap and diagnostics for the PocketTube catalog."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize_database(path: Path) -> None:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(database_path)
    try:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema)
        versions = [
            int(row["version"])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        if not versions:
            with conn:
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utc_now()),
                )
        elif versions[-1] != SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {versions[-1]} is incompatible with "
                f"application schema version {SCHEMA_VERSION}"
            )
    finally:
        conn.close()

def database_status(path: Path) -> dict[str, Any]:
    database_path = Path(path)
    if not database_path.is_file():
        return {
            "available": False,
            "compatible": False,
            "schemaVersion": None,
            "database": database_path.name,
        }
    conn = connect(database_path)
    try:
        version_row = conn.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()
        version = int(version_row["version"]) if version_row["version"] is not None else None
        latest = conn.execute(
            "SELECT * FROM import_runs ORDER BY import_id DESC LIMIT 1"
        ).fetchone()
        successful = conn.execute(
            """
            SELECT * FROM import_runs
            WHERE status = 'complete'
            ORDER BY import_id DESC
            LIMIT 1
            """
        ).fetchone()
        counts = dict(
            conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM groups) AS groups,
                  (SELECT COUNT(*) FROM group_playlists) AS memberships,
                  (SELECT COUNT(*) FROM playlist_references) AS playlists
                """
            ).fetchone()
        )
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        return {
            "available": True,
            "compatible": version == SCHEMA_VERSION,
            "schemaVersion": version,
            "database": database_path.name,
            "counts": counts,
            "latestImport": dict(latest) if latest is not None else None,
            "latestSuccessfulImport": dict(successful) if successful is not None else None,
            "integrity": integrity,
            "foreignKeyErrors": foreign_key_errors,
        }
    finally:
        conn.close()
