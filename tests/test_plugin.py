from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from yt_pockettube.importers import PocketTubeFormatError, import_export
from yt_pockettube.plugin import create_plugin
from yt_pockettube.queries import UNCATEGORIZED_GROUP_KEY
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


class FakeRuntime:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.stopped = False

    def stop_requested(self) -> bool:
        return self.stopped

    def log(self, level: str, message: str, subject_id: str = "") -> None:
        del subject_id
        self.messages.append((level, message))


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
                    "exports_directory": str(root / "exports"),
                }
            ),
            encoding="utf-8",
        )
        import_export(database, export)
        import_subscription_export(database, subscription_export)
        plugin = create_plugin()
        (root / "exports").mkdir()
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
            self.assertEqual(
                plugin.worker_processes,
                (
                    {
                        "id": "fetch-exports",
                        "name": "Fetch PocketTube exports",
                        "description": (
                            "Import new PocketTube Playlist Manager and Subscription "
                            "Manager JSON exports from the configured local exports "
                            "directory."
                        ),
                        "service": "local",
                        "max_in_flight": 1,
                        "admin_surface": "advanced",
                        "button_label": "Fetch PocketTube exports",
                    },
                ),
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
            self.assertEqual(len(projection["groups"]), 4)
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
            self.assertEqual(
                next(
                    group
                    for group in projection["groups"]
                    if group["group_key"] == UNCATEGORIZED_GROUP_KEY
                ),
                {
                    "group_key": UNCATEGORIZED_GROUP_KEY,
                    "name": "Uncategorized",
                    "parent_key": None,
                    "position": 2,
                    "icon": "",
                    "include_unmatched": True,
                },
            )
            self.assertFalse(
                any(
                    membership["group_key"] == UNCATEGORIZED_GROUP_KEY
                    for membership in projection["memberships"]
                )
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
            self.assertEqual(len(plugin.project_playlist_groups()["groups"]), 4)

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
            self.assertEqual(len(plugin.project_playlist_groups()["groups"]), 4)
            with self.assertRaisesRegex(RuntimeError, "no successful import"):
                plugin.project_channel_groups()
            response_status, response = plugin.handle_api(
                "GET", "channel-groups", {}
            )
            self.assertEqual(response_status, 503)
            self.assertIn("no successful import", response["error"])

    def test_fetch_exports_worker_imports_new_files_then_skips_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exports = root / "exports"
            exports.mkdir()
            database = root / "catalog.sqlite3"
            config = root / "yt_pockettube.config.json"
            playlist = exports / "youtube_playlist_manager_2026-08-05.json"
            subscriptions = (
                exports / "youtube_subscription_manager_2026-08-05.json"
            )
            shutil.copyfile(FIXTURE, playlist)
            shutil.copyfile(SUBSCRIPTION_FIXTURE, subscriptions)
            config.write_text(
                json.dumps(
                    {
                        "database": str(database),
                        "exports_directory": str(exports),
                    }
                ),
                encoding="utf-8",
            )
            plugin = create_plugin()
            plugin.start(FakeContext(root))
            runtime = FakeRuntime()

            plan = plugin.plan_worker("fetch-exports", object(), {})
            first = plugin.run_worker("fetch-exports", plan[0], runtime)
            second = plugin.run_worker("fetch-exports", plan[0], runtime)

            self.assertEqual(
                plan,
                [
                    {
                        "task_id": "exports-directory",
                        "subject_id": "PocketTube exports",
                        "title": "PocketTube exports",
                        "payload": {},
                    }
                ],
            )
            self.assertEqual(first["outcome"], "updated")
            self.assertEqual(first["found"], 2)
            self.assertEqual(first["failed"], 0)
            self.assertEqual(second["outcome"], "no_change")
            self.assertEqual(second["skipped"], 2)
            status = plugin.status()
            self.assertEqual(status["state"], "ready")
            self.assertEqual(
                status["database"]["counts"],
                {"groups": 3, "memberships": 3, "playlists": 3},
            )
            self.assertEqual(
                status["database"]["subscriptions"]["counts"],
                {"groups": 3, "memberships": 5, "channels": 4},
            )
            self.assertEqual(
                sum(level == "info" for level, _ in runtime.messages),
                2,
            )

    def test_fetch_exports_worker_continues_after_invalid_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exports = root / "exports"
            exports.mkdir()
            database = root / "catalog.sqlite3"
            config = root / "yt_pockettube.config.json"
            (exports / "youtube_playlist_manager_broken.json").write_text(
                "{broken",
                encoding="utf-8",
            )
            shutil.copyfile(
                SUBSCRIPTION_FIXTURE,
                exports / "youtube_subscription_manager_valid.json",
            )
            config.write_text(
                json.dumps(
                    {
                        "database": str(database),
                        "exports_directory": str(exports),
                    }
                ),
                encoding="utf-8",
            )
            plugin = create_plugin()
            plugin.start(FakeContext(root))
            runtime = FakeRuntime()

            result = plugin.run_worker(
                "fetch-exports",
                {"payload": {}},
                runtime,
            )

            self.assertEqual(result["outcome"], "partial_failure")
            self.assertEqual(result["found"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(
                plugin.status()["database"]["subscriptions"]["counts"],
                {"groups": 3, "memberships": 5, "channels": 4},
            )
            self.assertTrue(
                any(level == "error" for level, _ in runtime.messages)
            )


if __name__ == "__main__":
    unittest.main()
