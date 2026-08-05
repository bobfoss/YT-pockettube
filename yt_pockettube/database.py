"""SQLite bootstrap and diagnostics for the PocketTube catalog."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
INTEGRATION_CONTRACT_VERSION = 1


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


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def _migrate_to_2(conn: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS subscription_import_runs (
          import_id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_path TEXT NOT NULL,
          source_name TEXT NOT NULL,
          source_mtime_ns INTEGER,
          source_size INTEGER,
          source_sha256 TEXT NOT NULL DEFAULT '',
          started_at TEXT NOT NULL,
          finished_at TEXT,
          status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
          group_count INTEGER NOT NULL DEFAULT 0 CHECK (group_count >= 0),
          membership_count INTEGER NOT NULL DEFAULT 0 CHECK (membership_count >= 0),
          channel_count INTEGER NOT NULL DEFAULT 0 CHECK (channel_count >= 0),
          issue_count INTEGER NOT NULL DEFAULT 0 CHECK (issue_count >= 0),
          error TEXT NOT NULL DEFAULT ''
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS subscription_groups (
          group_key TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          parent_key TEXT REFERENCES subscription_groups(group_key) ON DELETE CASCADE,
          position INTEGER NOT NULL CHECK (position >= 0),
          icon TEXT NOT NULL DEFAULT '',
          import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS subscription_channels (
          channel_id TEXT PRIMARY KEY,
          import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS subscription_group_channels (
          group_key TEXT NOT NULL REFERENCES subscription_groups(group_key) ON DELETE CASCADE,
          channel_id TEXT NOT NULL REFERENCES subscription_channels(channel_id) ON DELETE CASCADE,
          position INTEGER NOT NULL CHECK (position >= 0),
          source_value TEXT NOT NULL,
          import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id),
          PRIMARY KEY (group_key, channel_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS subscription_import_issues (
          issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
          import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id) ON DELETE CASCADE,
          severity TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
          kind TEXT NOT NULL,
          group_key TEXT NOT NULL DEFAULT '',
          source_position INTEGER,
          source_value TEXT NOT NULL DEFAULT '',
          message TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_subscription_groups_parent_position
          ON subscription_groups(parent_key, position, group_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_subscription_group_channels_group_position
          ON subscription_group_channels(group_key, position, channel_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_subscription_group_channels_channel
          ON subscription_group_channels(channel_id, group_key)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_subscription_import_runs_started
          ON subscription_import_runs(started_at DESC, import_id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_subscription_import_issues_import
          ON subscription_import_issues(import_id, issue_id)
        """,
    )
    for statement in statements:
        conn.execute(statement)


MIGRATIONS = {2: _migrate_to_2}


def initialize_database(path: Path) -> None:
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(database_path)
    try:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        if not _table_exists(conn, "schema_migrations"):
            conn.executescript(schema)
            with conn:
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utc_now()),
                )
            return
        versions = [
            int(row["version"])
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        if not versions:
            conn.executescript(schema)
            with conn:
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utc_now()),
                )
            return
        current_version = versions[-1]
        if current_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {current_version} is incompatible with "
                f"application schema version {SCHEMA_VERSION}"
            )
        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise RuntimeError(f"No database migration is available for version {version}")
            with conn:
                migration(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
    finally:
        conn.close()


def database_status(
    path: Path,
    *,
    verify_integrity: bool = True,
) -> dict[str, Any]:
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
        version = (
            int(version_row["version"])
            if version_row["version"] is not None
            else None
        )
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
        subscription_counts = {"groups": 0, "memberships": 0, "channels": 0}
        subscription_latest = None
        subscription_successful = None
        if _table_exists(conn, "subscription_import_runs"):
            subscription_counts = dict(
                conn.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM subscription_groups) AS groups,
                      (SELECT COUNT(*) FROM subscription_group_channels) AS memberships,
                      (SELECT COUNT(*) FROM subscription_channels) AS channels
                    """
                ).fetchone()
            )
            subscription_latest = conn.execute(
                """
                SELECT * FROM subscription_import_runs
                ORDER BY import_id DESC LIMIT 1
                """
            ).fetchone()
            subscription_successful = conn.execute(
                """
                SELECT * FROM subscription_import_runs
                WHERE status = 'complete'
                ORDER BY import_id DESC LIMIT 1
                """
            ).fetchone()
        payload = {
            "available": True,
            "compatible": version == SCHEMA_VERSION,
            "schemaVersion": version,
            "database": database_path.name,
            "counts": counts,
            "latestImport": dict(latest) if latest is not None else None,
            "latestSuccessfulImport": dict(successful) if successful is not None else None,
            "subscriptions": {
                "counts": subscription_counts,
                "latestImport": (
                    dict(subscription_latest)
                    if subscription_latest is not None
                    else None
                ),
                "latestSuccessfulImport": (
                    dict(subscription_successful)
                    if subscription_successful is not None
                    else None
                ),
            },
        }
        if verify_integrity:
            payload["integrity"] = str(
                conn.execute("PRAGMA integrity_check").fetchone()[0]
            )
            payload["foreignKeyErrors"] = len(
                conn.execute("PRAGMA foreign_key_check").fetchall()
            )
        return payload
    finally:
        conn.close()
