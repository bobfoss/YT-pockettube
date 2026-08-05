from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yt_pockettube.database import (
    SCHEMA_VERSION,
    connect,
    database_status,
    initialize_database,
)


class DatabaseTests(unittest.TestCase):
    def test_fresh_database_has_current_schema_and_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "catalog.sqlite3"

            initialize_database(database)
            status = database_status(database)

            self.assertTrue(status["available"])
            self.assertTrue(status["compatible"])
            self.assertEqual(status["schemaVersion"], SCHEMA_VERSION)
            self.assertEqual(
                status["counts"],
                {"groups": 0, "memberships": 0, "playlists": 0},
            )
            self.assertEqual(
                status["subscriptions"]["counts"],
                {"groups": 0, "memberships": 0, "channels": 0},
            )
            self.assertEqual(status["integrity"], "ok")
            self.assertEqual(status["foreignKeyErrors"], 0)

            conn = connect(database)
            try:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                conn.close()
            self.assertTrue(
                {
                    "schema_migrations",
                    "import_runs",
                    "groups",
                    "playlist_references",
                    "group_playlists",
                    "import_issues",
                    "subscription_import_runs",
                    "subscription_groups",
                    "subscription_channels",
                    "subscription_group_channels",
                    "subscription_import_issues",
                }.issubset(tables)
            )

    def test_version_one_database_migrates_without_losing_playlist_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "catalog.sqlite3"
            schema = (
                Path(__file__).parents[1] / "yt_pockettube" / "schema.sql"
            ).read_text(encoding="utf-8")
            conn = connect(database)
            try:
                conn.executescript(schema)
                with conn:
                    conn.execute(
                        """
                        INSERT INTO schema_migrations(version, applied_at)
                        VALUES (1, '2026-01-01T00:00:00Z')
                        """
                    )
                    cursor = conn.execute(
                        """
                        INSERT INTO import_runs(
                          source_path, source_name, source_sha256, started_at,
                          finished_at, status, group_count
                        )
                        VALUES (
                          'playlist.json', 'playlist.json', 'hash',
                          '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z',
                          'complete', 1
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO groups(
                          group_key, name, parent_key, position, icon, import_id
                        )
                        VALUES ('Existing', 'Existing', NULL, 0, '', ?)
                        """,
                        (int(cursor.lastrowid),),
                    )
                conn.execute("DROP TABLE subscription_group_channels")
                conn.execute("DROP TABLE subscription_import_issues")
                conn.execute("DROP TABLE subscription_groups")
                conn.execute("DROP TABLE subscription_channels")
                conn.execute("DROP TABLE subscription_import_runs")
            finally:
                conn.close()

            initialize_database(database)

            conn = connect(database)
            try:
                versions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                group_name = conn.execute(
                    "SELECT name FROM groups WHERE group_key = 'Existing'"
                ).fetchone()[0]
                subscription_tables = {
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type = 'table' AND name LIKE 'subscription_%'
                        """
                    )
                }
            finally:
                conn.close()
            self.assertEqual(versions, [1, 2])
            self.assertEqual(group_name, "Existing")
            self.assertEqual(
                subscription_tables,
                {
                    "subscription_import_runs",
                    "subscription_groups",
                    "subscription_channels",
                    "subscription_group_channels",
                    "subscription_import_issues",
                },
            )


if __name__ == "__main__":
    unittest.main()
