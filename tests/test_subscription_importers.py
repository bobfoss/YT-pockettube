from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from yt_pockettube.database import connect, database_status
from yt_pockettube.importers import PocketTubeFormatError, import_export
from yt_pockettube.subscription_importers import (
    extract_channel_id,
    import_subscription_export,
    load_subscription_snapshot,
)


FIXTURE = Path(__file__).with_name("fixtures") / "subscription_manager.json"
PLAYLIST_FIXTURE = Path(__file__).with_name("fixtures") / "playlist_manager.json"


class SubscriptionImporterTests(unittest.TestCase):
    def test_channel_id_extraction_accepts_raw_ids_and_direct_urls(self) -> None:
        self.assertEqual(
            extract_channel_id("UCaaaaaaaaaaaaaaaaaaaaaa"),
            "UCaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(
            extract_channel_id(
                "https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb"
            ),
            "UCbbbbbbbbbbbbbbbbbbbbbb",
        )
        self.assertIsNone(extract_channel_id("https://www.youtube.com/@example"))
        self.assertIsNone(extract_channel_id("not a channel"))

    def test_parser_normalizes_nested_hierarchy_memberships_and_issues(self) -> None:
        snapshot = load_subscription_snapshot(FIXTURE)

        self.assertEqual(
            [(group.key, group.parent_key, group.position) for group in snapshot.groups],
            [
                ("Root", None, 0),
                ("Child", "Root", 0),
                ("Other", None, 1),
            ],
        )
        self.assertEqual(len(snapshot.memberships), 5)
        self.assertEqual(len(snapshot.channel_ids), 4)
        self.assertEqual(
            [issue.kind for issue in snapshot.issues],
            [
                "duplicate_subscription_group_membership",
                "non_text_channel_reference",
                "invalid_channel_reference",
            ],
        )

    def test_import_populates_subscription_state_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "catalog.sqlite3"

            result = import_subscription_export(database, FIXTURE)
            status = database_status(database)

            self.assertEqual(
                {
                    key: result[key]
                    for key in ("groups", "memberships", "channels", "issues")
                },
                {"groups": 3, "memberships": 5, "channels": 4, "issues": 3},
            )
            self.assertEqual(
                status["subscriptions"]["counts"],
                {"groups": 3, "memberships": 5, "channels": 4},
            )
            self.assertEqual(status["integrity"], "ok")
            self.assertEqual(status["foreignKeyErrors"], 0)
            self.assertEqual(
                status["subscriptions"]["latestImport"]["status"],
                "complete",
            )

            conn = connect(database)
            try:
                child = conn.execute(
                    """
                    SELECT parent_key, icon
                    FROM subscription_groups
                    WHERE group_key = 'Child'
                    """
                ).fetchone()
                issue_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM subscription_import_issues
                    WHERE import_id = ?
                    """,
                    (result["importId"],),
                ).fetchone()[0]
                source_rows = conn.execute(
                    """
                    SELECT DISTINCT import_id FROM subscription_groups
                    UNION
                    SELECT DISTINCT import_id FROM subscription_group_channels
                    """
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(tuple(child), ("Root", "spark"))
            self.assertEqual(issue_count, 3)
            self.assertEqual([row[0] for row in source_rows], [result["importId"]])

    def test_failed_reimport_preserves_last_successful_subscription_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "catalog.sqlite3"
            export = root / "subscriptions.json"
            shutil.copyfile(FIXTURE, export)
            first = import_subscription_export(database, export)
            export.write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(
                PocketTubeFormatError,
                "Invalid PocketTube subscription JSON",
            ):
                import_subscription_export(database, export)

            status = database_status(database)
            self.assertEqual(
                status["subscriptions"]["counts"],
                {"groups": 3, "memberships": 5, "channels": 4},
            )
            self.assertEqual(
                status["subscriptions"]["latestImport"]["status"],
                "failed",
            )
            self.assertEqual(
                status["subscriptions"]["latestSuccessfulImport"]["import_id"],
                first["importId"],
            )

    def test_subscription_import_does_not_replace_playlist_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "catalog.sqlite3"
            import_export(database, PLAYLIST_FIXTURE)

            import_subscription_export(database, FIXTURE)

            status = database_status(database)
            self.assertEqual(
                status["counts"],
                {"groups": 3, "memberships": 3, "playlists": 3},
            )
            self.assertEqual(
                status["subscriptions"]["counts"],
                {"groups": 3, "memberships": 5, "channels": 4},
            )

    def test_successful_reimport_replaces_only_subscription_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "catalog.sqlite3"
            export = root / "subscriptions.json"
            shutil.copyfile(FIXTURE, export)
            import_subscription_export(database, export)
            export.write_text(
                json.dumps(
                    {
                        "Replacement": ["UCeeeeeeeeeeeeeeeeeeeeee"],
                        "ysc_meta": {"Replacement": {"img": "new"}},
                        "ysc_settings": {"sub_groups": {"Replacement": {}}},
                    }
                ),
                encoding="utf-8",
            )

            second = import_subscription_export(database, export)

            status = database_status(database)
            self.assertEqual(
                status["subscriptions"]["counts"],
                {"groups": 1, "memberships": 1, "channels": 1},
            )
            self.assertEqual(
                status["subscriptions"]["latestImport"]["import_id"],
                second["importId"],
            )
            conn = connect(database)
            try:
                names = [
                    row[0]
                    for row in conn.execute("SELECT name FROM subscription_groups")
                ]
                run_count = conn.execute(
                    "SELECT COUNT(*) FROM subscription_import_runs"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(names, ["Replacement"])
            self.assertEqual(run_count, 2)

    def test_duplicate_group_in_nested_hierarchy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export = Path(temp_dir) / "duplicate.json"
            export.write_text(
                json.dumps(
                    {
                        "A": [],
                        "B": [],
                        "ysc_settings": {
                            "sub_groups": {
                                "A": {"B": {}},
                                "B": {},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(PocketTubeFormatError, "more than once"):
                load_subscription_snapshot(export)


if __name__ == "__main__":
    unittest.main()
