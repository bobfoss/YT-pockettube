"""JSON configuration for the standalone PocketTube catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("yt_pockettube.config.json")
DEFAULT_CONFIG: dict[str, Any] = {
    "database": "yt_pockettube.sqlite3",
    "export": "",
    "subscription_export": "",
}


class ConfigError(ValueError):
    """Raised when local configuration is missing or invalid."""


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise ConfigError(
            f"Configuration not found: {config_path}. "
            "Copy yt_pockettube.config.example.json to yt_pockettube.config.json."
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON configuration: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("Configuration must be a JSON object")
    config = {**DEFAULT_CONFIG, **raw, "_config_path": str(config_path)}
    for key in ("database", "export", "subscription_export"):
        if not isinstance(config.get(key), str):
            raise ConfigError(f"Configuration value {key!r} must be a string")
    return config


def config_path(
    config: dict[str, Any],
    key: str,
    *,
    required: bool = True,
) -> Path | None:
    value = str(config.get(key) or "").strip()
    if not value:
        if required:
            raise ConfigError(f"Configuration value {key!r} is required")
        return None
    path = Path(value)
    if not path.is_absolute():
        config_file = Path(str(config["_config_path"]))
        path = config_file.parent / path
    return path.resolve()
