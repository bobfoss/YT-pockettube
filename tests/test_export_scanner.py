from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from yt_pockettube.export_scanner import classify_export, scan_exports
from yt_pockettube.importers import PocketTubeFormatError, import_export


FIXTURE = Path(__file__).with_name("fixtures") / "playlist_manager.json"
SUBSCRIPTION_FIXTURE = (
    Path(__file__).with_name("fixtures") / "subscription_manager.json"
)


class ExportScannerTests(unittest.TestCase):
    def test_classifies_standard_pockettube_export_names(self) -> None:
        self.assertEqual(
            classify_export(Path("youtube_playlist_manager_2026-08-05.json")),
            "playlist",
        )
        self.assertEqual(
            classify_export(Path("youtube_subscription_manager_2026-08-05.JSON")),
            "subscription",
        )
        self.assertIsNone(classify_export(Path("unrelated.json")))
        self.assertIsNone(classify_export(Path("youtube_playlist_manager.txt")))

    def test_discovers_unseen_exports_oldest_first_per_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exports = root / "exports"
            exports.mkdir()
            database = root / "catalog.sqlite3"
            older = exports / "youtube_playlist_manager_older.json"
            newer = exports / "youtube_playlist_manager_newer.json"
            subscription = exports / "youtube_subscription_manager.json"
            shutil.copyfile(FIXTURE, older)
            newer.write_bytes(FIXTURE.read_bytes() + b"\n")
            shutil.copyfile(SUBSCRIPTION_FIXTURE, subscription)
            (exports / "notes.json").write_text("{}", encoding="utf-8")
            os.utime(older, ns=(1_000_000_000, 1_000_000_000))
            os.utime(newer, ns=(2_000_000_000, 2_000_000_000))

            first = scan_exports(database, exports)

            self.assertEqual(
                [(item.kind, item.source.name) for item in first.candidates],
                [
                    ("playlist", older.name),
                    ("playlist", newer.name),
                    ("subscription", subscription.name),
                ],
            )
            self.assertEqual(first.ignored, 1)
            self.assertEqual(first.already_imported, 0)

            import_export(database, older)
            duplicate = exports / "youtube_playlist_manager_copy.json"
            shutil.copyfile(older, duplicate)
            second = scan_exports(database, exports)

            self.assertEqual(
                [item.source.name for item in second.candidates],
                [newer.name, subscription.name],
            )
            self.assertEqual(second.already_imported, 2)

    def test_missing_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(FileNotFoundError, "directory not found"):
                scan_exports(root / "catalog.sqlite3", root / "missing")

    def test_failed_import_remains_eligible_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exports = root / "exports"
            exports.mkdir()
            database = root / "catalog.sqlite3"
            broken = exports / "youtube_playlist_manager_broken.json"
            broken.write_text("{broken", encoding="utf-8")
            with self.assertRaises(PocketTubeFormatError):
                import_export(database, broken)

            scan = scan_exports(database, exports)

            self.assertEqual(
                [candidate.source.name for candidate in scan.candidates],
                [broken.name],
            )
            self.assertEqual(scan.already_imported, 0)


if __name__ == "__main__":
    unittest.main()
