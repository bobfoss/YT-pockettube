from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yt_pockettube.config import ConfigError, config_path, load_config


class ConfigTests(unittest.TestCase):
    def test_relative_paths_resolve_from_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_file = root / "settings" / "yt_pockettube.config.json"
            config_file.parent.mkdir()
            config_file.write_text(
                json.dumps(
                    {
                        "database": "runtime/catalog.sqlite3",
                        "export": "../exports/pockettube.json",
                        "subscription_export": "../exports/subscriptions.json",
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(config_file)

            self.assertEqual(
                config_path(config, "database"),
                (config_file.parent / "runtime/catalog.sqlite3").resolve(),
            )
            self.assertEqual(
                config_path(config, "export"),
                (config_file.parent / "../exports/pockettube.json").resolve(),
            )
            self.assertEqual(
                config_path(config, "subscription_export"),
                (config_file.parent / "../exports/subscriptions.json").resolve(),
            )

    def test_missing_configuration_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            with self.assertRaisesRegex(ConfigError, "Copy"):
                load_config(missing)


if __name__ == "__main__":
    unittest.main()
