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
                }.issubset(tables)
            )


if __name__ == "__main__":
    unittest.main()
