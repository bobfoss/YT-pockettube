from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from yt_pockettube.importers import PocketTubeFormatError, import_export
from yt_pockettube.plugin import create_plugin
from yt_pockettube.subscription_importers import import_subscription_export


FIXTURE = Path(__file__).with_name("fixtures") / "playlist_manager.json"
SUBSCRIPTION_FIXTURE = (
    Path(__file__).with_name("fixtures") / "subscription_manager.json"
)


class FakeContext:
    def __init__(self, root: Path, config: str = "yt_pockettube.config.json") -> None:
        self.root = root
        self.plugin_config = {"config": config}

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path


class PluginTests(unittest.TestCase):
    def create_ready_plugin(self, root: Path):
        database = root / "catalog.sqlite3"
        export = root / "pockettube.json"
        subscription_export = root / "subscriptions.json"
        config = root / "yt_pockettube.config.json"
        shutil.copyfile(FIXTURE, export)
        shutil.copyfile(SUBSCRIPTION_FIXTURE, subscription_export)
        config.write_text(
            json.dumps(
                {
                    "database": str(database),
                    "export": str(export),
                    "subscription_export": str(subscription_export),
                }
            ),
            encoding="utf-8",
        )
        import_export(database, export)
        import_subscription_export(database, subscription_export)
        plugin = create_plugin()
        plugin.start(FakeContext(root))
        return plugin, database, export

    def test_plugin_reports_ready_status_and_projects_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin, _, _ = self.create_ready_plugin(root)

            status = plugin.status()
            projection = plugin.project_playlist_groups()
            channel_projection = plugin.project_channel_groups()

            self.assertEqual(plugin.plugin_id, "pockettube")
            self.assertEqual(plugin.plugin_api_version, 2)
            self.assertEqual(
                plugin.capabilities,
                frozenset({"channel_groups", "playlist_groups"}),
            )
            self.assertEqual(status["state"], "ready")
            self.assertEqual(
                status["database"]["counts"],
                {"groups": 3, "memberships": 3, "playlists": 3},
            )
            self.assertNotIn("source_path", json.dumps(status).casefold())
            self.assertEqual(
                status["database"]["subscriptions"]["counts"],
                {"groups": 3, "memberships": 5, "channels": 4},
            )
            self.assertEqual(len(projection["groups"]), 3)
            self.assertEqual(len(projection["memberships"]), 3)
            self.assertEqual(len(channel_projection["groups"]), 3)
            self.assertEqual(len(channel_projection["memberships"]), 5)
            self.assertTrue(channel_projection["revision"].startswith("1:"))
            self.assertTrue(projection["revision"].startswith("1:"))
            self.assertEqual(
                next(
                    group
                    for group in projection["groups"]
                    if group["group_key"] == "Child"
                )["parent_key"],
                "Parent",
            )

            response_status, response = plugin.handle_api("GET", "groups", {})
            self.assertEqual(response_status, 200)
            self.assertEqual(response, projection)
            response_status, response = plugin.handle_api(
                "GET", "channel-groups", {}
            )
            self.assertEqual(response_status, 200)
            self.assertEqual(response, channel_projection)
            self.assertIsNone(plugin.handle_api("POST", "groups", {}))
            self.assertIsNone(plugin.handle_api("GET", "missing", {}))

            plugin.shutdown()
            self.assertEqual(plugin.status()["state"], "stopped")

    def test_plugin_serves_previous_catalog_after_failed_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin, database, export = self.create_ready_plugin(root)
            export.write_text("{broken", encoding="utf-8")
            with self.assertRaises(PocketTubeFormatError):
                import_export(database, export)

            status = plugin.status()

            self.assertEqual(status["state"], "ready")
            self.assertIn("last successful", status["message"])
            self.assertEqual(len(plugin.project_playlist_groups()["groups"]), 3)

    def test_plugin_reports_missing_database_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "yt_pockettube.config.json"
            database = root / "missing.sqlite3"
            config.write_text(
                json.dumps({"database": str(database), "export": "missing.json"}),
                encoding="utf-8",
            )
            plugin = create_plugin()
            plugin.start(FakeContext(root))

            status = plugin.status()

            self.assertEqual(status["state"], "unavailable")
            self.assertFalse(database.exists())
            with self.assertRaisesRegex(RuntimeError, "not available"):
                plugin.project_playlist_groups()

    def test_missing_subscription_import_does_not_disable_playlist_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "catalog.sqlite3"
            export = root / "pockettube.json"
            config = root / "yt_pockettube.config.json"
            shutil.copyfile(FIXTURE, export)
            config.write_text(
                json.dumps({"database": str(database), "export": str(export)}),
                encoding="utf-8",
            )
            import_export(database, export)
            plugin = create_plugin()
            plugin.start(FakeContext(root))

            self.assertEqual(plugin.status()["state"], "ready")
            self.assertEqual(len(plugin.project_playlist_groups()["groups"]), 3)
            with self.assertRaisesRegex(RuntimeError, "no successful import"):
                plugin.project_channel_groups()
            response_status, response = plugin.handle_api(
                "GET", "channel-groups", {}
            )
            self.assertEqual(response_status, 503)
            self.assertIn("no successful import", response["error"])


if __name__ == "__main__":
    unittest.main()
