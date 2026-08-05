from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from yt_pockettube.database import connect, database_status
from yt_pockettube.importers import (
    PocketTubeFormatError,
    extract_playlist_id,
    import_export,
    load_snapshot,
)


FIXTURE = Path(__file__).with_name("fixtures") / "playlist_manager.json"


class ImporterTests(unittest.TestCase):
    def test_playlist_id_extraction_accepts_raw_ids_and_urls(self) -> None:
        self.assertEqual(
            extract_playlist_id("PLalpha0000000001"),
            "PLalpha0000000001",
        )
        self.assertEqual(
            extract_playlist_id(
                "https://www.youtube.com/playlist?list=PLbeta00000000002"
            ),
            "PLbeta00000000002",
        )
        self.assertIsNone(extract_playlist_id("not a playlist"))

    def test_parser_normalizes_hierarchy_memberships_and_issues(self) -> None:
        snapshot = load_snapshot(FIXTURE)

        self.assertEqual(
            [(group.key, group.parent_key, group.position) for group in snapshot.groups],
            [
                ("Parent", None, 0),
                ("Child", "Parent", 0),
                ("Standalone", None, 1),
            ],
        )
        self.assertEqual(len(snapshot.memberships), 3)
        self.assertEqual(len(snapshot.playlist_ids), 3)
        self.assertEqual(
            [issue.kind for issue in snapshot.issues],
            [
                "duplicate_group_membership",
                "non_text_playlist_reference",
                "invalid_playlist_reference",
            ],
        )

    def test_import_populates_current_state_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "catalog.sqlite3"

            result = import_export(database, FIXTURE)
            status = database_status(database)

            self.assertEqual(
                {key: result[key] for key in ("groups", "memberships", "playlists", "issues")},
                {"groups": 3, "memberships": 3, "playlists": 3, "issues": 3},
            )
            self.assertEqual(status["counts"], {"groups": 3, "memberships": 3, "playlists": 3})
            self.assertEqual(status["integrity"], "ok")
            self.assertEqual(status["foreignKeyErrors"], 0)
            self.assertEqual(status["latestImport"]["status"], "complete")

            conn = connect(database)
            try:
                child = conn.execute(
                    "SELECT parent_key, icon FROM groups WHERE group_key = 'Child'"
                ).fetchone()
                issue_count = conn.execute(
                    "SELECT COUNT(*) FROM import_issues WHERE import_id = ?",
                    (result["importId"],),
                ).fetchone()[0]
                source_rows = conn.execute(
                    "SELECT DISTINCT import_id FROM groups UNION SELECT DISTINCT import_id FROM group_playlists"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(tuple(child), ("Parent", "spark"))
            self.assertEqual(issue_count, 3)
            self.assertEqual([row[0] for row in source_rows], [result["importId"]])

    def test_failed_reimport_preserves_last_successful_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "catalog.sqlite3"
            export = root / "pockettube.json"
            shutil.copyfile(FIXTURE, export)
            first = import_export(database, export)
            export.write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(PocketTubeFormatError, "Invalid PocketTube JSON"):
                import_export(database, export)

            status = database_status(database)
            self.assertEqual(status["counts"], {"groups": 3, "memberships": 3, "playlists": 3})
            self.assertEqual(status["latestImport"]["status"], "failed")
            self.assertEqual(
                status["latestSuccessfulImport"]["import_id"],
                first["importId"],
            )

    def test_successful_reimport_atomically_replaces_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "catalog.sqlite3"
            export = root / "pockettube.json"
            shutil.copyfile(FIXTURE, export)
            import_export(database, export)
            export.write_text(
                json.dumps(
                    {
                        "Replacement": ["PLreplacement00001"],
                        "ysc_meta": {"Replacement": {"img": "new"}},
                        "ysc_settings": {"sub_groups": {}},
                    }
                ),
                encoding="utf-8",
            )

            second = import_export(database, export)

            status = database_status(database)
            self.assertEqual(status["counts"], {"groups": 1, "memberships": 1, "playlists": 1})
            self.assertEqual(status["latestImport"]["import_id"], second["importId"])
            conn = connect(database)
            try:
                names = [row[0] for row in conn.execute("SELECT name FROM groups")]
                run_count = conn.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(names, ["Replacement"])
            self.assertEqual(run_count, 2)

    def test_invalid_hierarchy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export = Path(temp_dir) / "cycle.json"
            export.write_text(
                json.dumps(
                    {
                        "A": [],
                        "B": [],
                        "ysc_settings": {
                            "sub_groups": {"A": {"B": True}, "B": {"A": True}}
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PocketTubeFormatError, "cycle"):
                load_snapshot(export)


if __name__ == "__main__":
    unittest.main()
