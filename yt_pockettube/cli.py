"""Command-line interface for the standalone PocketTube catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import DEFAULT_CONFIG_PATH, ConfigError, config_path, load_config
from .database import database_status, initialize_database
from .importers import PocketTubeFormatError, import_export


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt-pockettube")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to yt_pockettube.config.json",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Initialize the configured database")
    import_parser = subparsers.add_parser(
        "import", help="Import the configured PocketTube export"
    )
    import_parser.add_argument(
        "--export",
        type=Path,
        help="Override the export path from configuration",
    )
    subparsers.add_parser("status", help="Show database and latest import status")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        database = config_path(config, "database")
        assert database is not None
        if args.command == "init":
            initialize_database(database)
            payload = database_status(database)
        elif args.command == "import":
            export = args.export.resolve() if args.export else config_path(config, "export")
            assert export is not None
            payload = import_export(database, export)
        else:
            payload = database_status(database)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ConfigError, PocketTubeFormatError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
