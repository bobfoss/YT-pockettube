"""PocketTube Subscription Manager parsing and atomic database import."""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import connect, initialize_database, utc_now
from .importers import ImportIssue, PocketTubeFormatError, SourceDocument, read_source


MAX_GROUPS = 10_000
MAX_MEMBERSHIPS = 1_000_000
MAX_GROUP_NAME_LENGTH = 500
MAX_ICON_LENGTH = 10_000
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")


@dataclass(frozen=True)
class SubscriptionGroupRecord:
    key: str
    name: str
    parent_key: str | None
    position: int
    icon: str


@dataclass(frozen=True)
class ChannelMembershipRecord:
    group_key: str
    channel_id: str
    position: int
    source_value: str


@dataclass(frozen=True)
class SubscriptionSnapshot:
    source: SourceDocument
    groups: tuple[SubscriptionGroupRecord, ...]
    memberships: tuple[ChannelMembershipRecord, ...]
    channel_ids: frozenset[str]
    issues: tuple[ImportIssue, ...]


def extract_channel_id(value: str) -> str | None:
    candidate = value.strip()
    if CHANNEL_ID.fullmatch(candidate):
        return candidate
    parsed = urllib.parse.urlparse(candidate)
    hostname = (parsed.hostname or "").casefold()
    if hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return None
    path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(path_parts) == 2 and path_parts[0].casefold() == "channel":
        channel_id = path_parts[1].strip()
        return channel_id if CHANNEL_ID.fullmatch(channel_id) else None
    return None


def _group_name(value: Any, label: str) -> str:
    name = str(value).strip()
    if not name:
        raise PocketTubeFormatError(f"{label} must not be empty")
    if len(name) > MAX_GROUP_NAME_LENGTH:
        raise PocketTubeFormatError(
            f"{label} exceeds {MAX_GROUP_NAME_LENGTH} characters"
        )
    return name


def _combined_group_metadata(export: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    keys = [
        key
        for key in export
        if key == "ysc_meta" or key.startswith("ysc_meta_meta_parts_")
    ]
    for key in keys:
        part = export.get(key) or {}
        if not isinstance(part, dict):
            raise PocketTubeFormatError(f"{key} must be an object when present")
        for raw_name, value in part.items():
            name = _group_name(raw_name, f"Group name in {key}")
            if name in metadata:
                raise PocketTubeFormatError(
                    f"Group metadata for {name!r} appears in multiple sections"
                )
            metadata[name] = value
    return metadata


def parse_subscription_source(source: SourceDocument) -> SubscriptionSnapshot:
    try:
        export = json.loads(source.content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PocketTubeFormatError(f"Invalid PocketTube subscription JSON: {exc}") from exc
    if not isinstance(export, dict):
        raise PocketTubeFormatError(
            "PocketTube subscription export must be a JSON object"
        )

    group_lists: dict[str, list[Any]] = {}
    for raw_name, values in export.items():
        if str(raw_name).startswith("ysc_"):
            continue
        name = _group_name(raw_name, "Subscription group name")
        if not isinstance(values, list):
            raise PocketTubeFormatError(
                f"Subscription group {name!r} must contain a list of channel IDs"
            )
        group_lists[name] = values

    settings = export.get("ysc_settings") or {}
    if not isinstance(settings, dict):
        raise PocketTubeFormatError("ysc_settings must be an object when present")
    raw_sub_groups = settings.get("sub_groups") or {}
    if not isinstance(raw_sub_groups, dict):
        raise PocketTubeFormatError("ysc_settings.sub_groups must be an object")
    metadata = _combined_group_metadata(export)
    issues: list[ImportIssue] = []
    groups: list[SubscriptionGroupRecord] = []
    seen_groups: set[str] = set()

    def add_group(
        raw_name: Any,
        raw_children: Any,
        parent_key: str | None,
        position: int,
    ) -> None:
        name = _group_name(raw_name, "Subscription group name")
        if name in seen_groups:
            raise PocketTubeFormatError(
                f"Subscription group {name!r} appears more than once in the hierarchy"
            )
        if not isinstance(raw_children, dict):
            raise PocketTubeFormatError(
                f"Sub-groups for subscription group {name!r} must be an object"
            )
        if len(groups) >= MAX_GROUPS:
            raise PocketTubeFormatError(
                f"Subscription export contains more than {MAX_GROUPS} groups"
            )
        raw_meta = metadata.get(name) or {}
        if not isinstance(raw_meta, dict):
            issues.append(
                ImportIssue(
                    "warning",
                    "invalid_subscription_group_metadata",
                    name,
                    None,
                    "",
                    "Group metadata is not an object; icon was ignored",
                )
            )
            raw_meta = {}
        raw_icon = raw_meta.get("img") or ""
        if not isinstance(raw_icon, str):
            issues.append(
                ImportIssue(
                    "warning",
                    "invalid_subscription_group_icon",
                    name,
                    None,
                    "",
                    "Group icon is not text; icon was ignored",
                )
            )
            raw_icon = ""
        icon = raw_icon[:MAX_ICON_LENGTH]
        if len(raw_icon) > MAX_ICON_LENGTH:
            issues.append(
                ImportIssue(
                    "warning",
                    "truncated_subscription_group_icon",
                    name,
                    None,
                    "",
                    f"Group icon exceeded {MAX_ICON_LENGTH} characters",
                )
            )
        seen_groups.add(name)
        groups.append(SubscriptionGroupRecord(name, name, parent_key, position, icon))
        for child_position, (child_name, grandchildren) in enumerate(
            raw_children.items()
        ):
            add_group(child_name, grandchildren, name, child_position)

    if raw_sub_groups:
        for root_position, (root_name, children) in enumerate(raw_sub_groups.items()):
            add_group(root_name, children, None, root_position)

    missing_names = [name for name in group_lists if name not in seen_groups]
    for root_position, name in enumerate(missing_names, start=len(raw_sub_groups)):
        add_group(name, {}, None, root_position)

    collection = export.get("ysc_collection") or {}
    if not isinstance(collection, dict):
        raise PocketTubeFormatError("ysc_collection must be an object when present")
    collection_names = [
        _group_name(raw_name, "Group name in ysc_collection")
        for raw_name in collection
    ]
    for root_position, name in enumerate(
        (name for name in collection_names if name not in seen_groups),
        start=len([group for group in groups if group.parent_key is None]),
    ):
        add_group(name, {}, None, root_position)

    memberships: list[ChannelMembershipRecord] = []
    channel_ids: set[str] = set()
    for group in groups:
        seen_channel_ids: set[str] = set()
        for source_position, raw_value in enumerate(group_lists.get(group.key, ())):
            if len(memberships) >= MAX_MEMBERSHIPS:
                raise PocketTubeFormatError(
                    "Subscription export contains more than "
                    f"{MAX_MEMBERSHIPS} memberships"
                )
            if not isinstance(raw_value, str):
                issues.append(
                    ImportIssue(
                        "warning",
                        "non_text_channel_reference",
                        group.key,
                        source_position,
                        "",
                        "Channel reference is not text and was skipped",
                    )
                )
                continue
            channel_id = extract_channel_id(raw_value)
            if channel_id is None:
                issues.append(
                    ImportIssue(
                        "warning",
                        "invalid_channel_reference",
                        group.key,
                        source_position,
                        raw_value[:2_000],
                        "Channel reference does not contain a canonical YouTube channel ID",
                    )
                )
                continue
            if channel_id in seen_channel_ids:
                issues.append(
                    ImportIssue(
                        "warning",
                        "duplicate_subscription_group_membership",
                        group.key,
                        source_position,
                        raw_value[:2_000],
                        "Duplicate channel reference in one group was skipped",
                    )
                )
                continue
            seen_channel_ids.add(channel_id)
            channel_ids.add(channel_id)
            memberships.append(
                ChannelMembershipRecord(
                    group.key,
                    channel_id,
                    len(seen_channel_ids) - 1,
                    raw_value[:2_000],
                )
            )

    return SubscriptionSnapshot(
        source=source,
        groups=tuple(groups),
        memberships=tuple(memberships),
        channel_ids=frozenset(channel_ids),
        issues=tuple(issues),
    )


def load_subscription_snapshot(path: Path) -> SubscriptionSnapshot:
    return parse_subscription_source(read_source(path))


def _start_subscription_import(
    conn: sqlite3.Connection,
    source: SourceDocument,
) -> int:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO subscription_import_runs(
              source_path, source_name, source_mtime_ns, source_size,
              source_sha256, started_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'running')
            """,
            (
                str(source.path),
                source.name,
                source.mtime_ns,
                source.size,
                source.sha256,
                utc_now(),
            ),
        )
    return int(cursor.lastrowid)


def _fail_subscription_import(
    conn: sqlite3.Connection,
    import_id: int,
    error: str,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE subscription_import_runs
            SET status = 'failed', finished_at = ?, error = ?
            WHERE import_id = ?
            """,
            (utc_now(), str(error)[:10_000], import_id),
        )


def import_subscription_export(
    database_path: Path,
    export_path: Path,
) -> dict[str, Any]:
    initialize_database(database_path)
    source = read_source(export_path)
    conn = connect(database_path)
    import_id = _start_subscription_import(conn, source)
    try:
        snapshot = parse_subscription_source(source)
        with conn:
            conn.execute("DELETE FROM subscription_group_channels")
            conn.execute("DELETE FROM subscription_groups")
            conn.execute("DELETE FROM subscription_channels")
            conn.executemany(
                """
                INSERT INTO subscription_groups(
                  group_key, name, parent_key, position, icon, import_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        group.key,
                        group.name,
                        group.parent_key,
                        group.position,
                        group.icon,
                        import_id,
                    )
                    for group in snapshot.groups
                ),
            )
            conn.executemany(
                """
                INSERT INTO subscription_channels(channel_id, import_id)
                VALUES (?, ?)
                """,
                (
                    (channel_id, import_id)
                    for channel_id in sorted(snapshot.channel_ids)
                ),
            )
            conn.executemany(
                """
                INSERT INTO subscription_group_channels(
                  group_key, channel_id, position, source_value, import_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        membership.group_key,
                        membership.channel_id,
                        membership.position,
                        membership.source_value,
                        import_id,
                    )
                    for membership in snapshot.memberships
                ),
            )
            conn.executemany(
                """
                INSERT INTO subscription_import_issues(
                  import_id, severity, kind, group_key, source_position,
                  source_value, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        import_id,
                        issue.severity,
                        issue.kind,
                        issue.group_key,
                        issue.source_position,
                        issue.source_value,
                        issue.message,
                    )
                    for issue in snapshot.issues
                ),
            )
            conn.execute(
                """
                UPDATE subscription_import_runs
                SET status = 'complete', finished_at = ?,
                    group_count = ?, membership_count = ?, channel_count = ?,
                    issue_count = ?, error = ''
                WHERE import_id = ?
                """,
                (
                    utc_now(),
                    len(snapshot.groups),
                    len(snapshot.memberships),
                    len(snapshot.channel_ids),
                    len(snapshot.issues),
                    import_id,
                ),
            )
        return {
            "importId": import_id,
            "status": "complete",
            "source": source.name,
            "sourceSha256": source.sha256,
            "groups": len(snapshot.groups),
            "memberships": len(snapshot.memberships),
            "channels": len(snapshot.channel_ids),
            "issues": len(snapshot.issues),
        }
    except Exception as exc:
        _fail_subscription_import(conn, import_id, str(exc))
        raise
    finally:
        conn.close()
