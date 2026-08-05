"""YT Library plugin entry point for PocketTube organization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from .config import config_path, load_config
from .database import (
    INTEGRATION_CONTRACT_VERSION,
    SCHEMA_VERSION,
    database_status,
)
from .queries import playlist_group_projection, subscription_group_projection


def _public_import(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "importId": value.get("import_id"),
        "status": str(value.get("status") or ""),
        "sourceName": str(value.get("source_name") or ""),
        "finishedAt": str(value.get("finished_at") or ""),
        "groupCount": int(value.get("group_count") or 0),
        "membershipCount": int(value.get("membership_count") or 0),
        "playlistCount": int(value.get("playlist_count") or 0),
        "issueCount": int(value.get("issue_count") or 0),
    }


def _public_subscription_import(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "importId": value.get("import_id"),
        "status": str(value.get("status") or ""),
        "sourceName": str(value.get("source_name") or ""),
        "finishedAt": str(value.get("finished_at") or ""),
        "groupCount": int(value.get("group_count") or 0),
        "membershipCount": int(value.get("membership_count") or 0),
        "channelCount": int(value.get("channel_count") or 0),
        "issueCount": int(value.get("issue_count") or 0),
    }


class YTPocketTubePlugin:
    plugin_id = "pockettube"
    plugin_name = "YT PocketTube"
    plugin_version = __version__
    plugin_api_version = 2
    capabilities = frozenset({"channel_groups", "playlist_groups"})
    browser_assets: tuple[dict[str, str], ...] = ()

    def __init__(self) -> None:
        self._database_path: Path | None = None

    def start(self, context: Any) -> None:
        configured_path = str(context.plugin_config.get("config") or "").strip()
        own_config_path = (
            context.resolve_path(configured_path) if configured_path else None
        )
        own_config = load_config(own_config_path) if own_config_path else load_config()
        self._database_path = config_path(own_config, "database")

    def status(self) -> dict[str, Any]:
        if self._database_path is None:
            return {"state": "stopped", "message": "Plugin has not been started"}
        status = database_status(self._database_path, verify_integrity=False)
        latest = _public_import(status.get("latestImport"))
        successful = _public_import(status.get("latestSuccessfulImport"))
        subscription_status = status.get("subscriptions") or {}
        subscription_latest = _public_subscription_import(
            subscription_status.get("latestImport")
        )
        subscription_successful = _public_subscription_import(
            subscription_status.get("latestSuccessfulImport")
        )
        available = bool(status.get("available"))
        compatible = bool(status.get("compatible"))
        state = (
            "ready"
            if available
            and compatible
            and (successful or subscription_successful)
            else "unavailable"
        )
        if available and not compatible:
            state = "incompatible"
        payload = {
            "state": state,
            "capabilities": sorted(self.capabilities),
            "database": {
                "available": available,
                "compatible": compatible,
                "schemaVersion": status.get("schemaVersion"),
                "expectedSchemaVersion": SCHEMA_VERSION,
                "integrationContractVersion": INTEGRATION_CONTRACT_VERSION,
                "name": status.get("database"),
                "counts": status.get("counts")
                or {"groups": 0, "memberships": 0, "playlists": 0},
                "latestImport": latest,
                "latestSuccessfulImport": successful,
                "subscriptions": {
                    "counts": subscription_status.get("counts")
                    or {"groups": 0, "memberships": 0, "channels": 0},
                    "latestImport": subscription_latest,
                    "latestSuccessfulImport": subscription_successful,
                },
            },
        }
        failed_catalogs = []
        if latest and latest["status"] == "failed" and successful:
            failed_catalogs.append("playlist")
        if (
            subscription_latest
            and subscription_latest["status"] == "failed"
            and subscription_successful
        ):
            failed_catalogs.append("subscription")
        if state == "ready" and failed_catalogs:
            payload["message"] = (
                "Serving the last successful PocketTube "
                f"{' and '.join(failed_catalogs)} import"
            )
        elif state == "unavailable" and not available:
            payload["message"] = "PocketTube database is not available"
        elif state == "unavailable" and not successful:
            payload["message"] = "PocketTube database has no successful import"
        return payload

    def project_playlist_groups(self) -> dict[str, Any]:
        if self._database_path is None:
            raise RuntimeError("Plugin has not been started")
        status = self.status()
        database = status.get("database") or {}
        if not database.get("available") or not database.get("compatible"):
            raise RuntimeError(
                str(status.get("message") or "YT PocketTube is not ready")
            )
        if not database.get("latestSuccessfulImport"):
            raise RuntimeError("PocketTube catalog has no successful import")
        return playlist_group_projection(self._database_path)

    def project_channel_groups(self) -> dict[str, Any]:
        if self._database_path is None:
            raise RuntimeError("Plugin has not been started")
        status = self.status()
        database = status.get("database") or {}
        if not database.get("available") or not database.get("compatible"):
            raise RuntimeError(
                str(status.get("message") or "YT PocketTube is not ready")
            )
        subscriptions = database.get("subscriptions") or {}
        if not subscriptions.get("latestSuccessfulImport"):
            raise RuntimeError(
                "PocketTube subscription catalog has no successful import"
            )
        return subscription_group_projection(self._database_path)

    def handle_api(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
    ) -> tuple[int, Any] | None:
        del query
        if method != "GET":
            return None
        if path == "status":
            return 200, self.status()
        if path == "groups":
            try:
                return 200, self.project_playlist_groups()
            except RuntimeError as exc:
                return 503, {"error": str(exc), "plugin": self.status()}
        if path == "channel-groups":
            try:
                return 200, self.project_channel_groups()
            except RuntimeError as exc:
                return 503, {"error": str(exc), "plugin": self.status()}
        return None

    def shutdown(self) -> None:
        self._database_path = None


def create_plugin() -> YTPocketTubePlugin:
    return YTPocketTubePlugin()
