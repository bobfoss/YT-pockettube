"""PocketTube Playlist Manager export parsing and atomic database import."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import connect, initialize_database, utc_now


MAX_EXPORT_BYTES = 50 * 1024 * 1024
MAX_GROUPS = 10_000
MAX_MEMBERSHIPS = 1_000_000
MAX_GROUP_NAME_LENGTH = 500
MAX_ICON_LENGTH = 10_000
PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{2,200}")


class PocketTubeFormatError(ValueError):
    """Raised when an export cannot produce a safe current-state snapshot."""


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    name: str
    mtime_ns: int
    size: int
    sha256: str
    content: bytes


@dataclass(frozen=True)
class GroupRecord:
    key: str
    name: str
    parent_key: str | None
    position: int
    icon: str


@dataclass(frozen=True)
class MembershipRecord:
    group_key: str
    playlist_id: str
    position: int
    source_value: str


@dataclass(frozen=True)
class ImportIssue:
    severity: str
    kind: str
    group_key: str
    source_position: int | None
    source_value: str
    message: str


@dataclass(frozen=True)
class PocketTubeSnapshot:
    source: SourceDocument
    groups: tuple[GroupRecord, ...]
    memberships: tuple[MembershipRecord, ...]
    playlist_ids: frozenset[str]
    issues: tuple[ImportIssue, ...]


def read_source(path: Path) -> SourceDocument:
    source_path = Path(path).resolve()
    try:
        before = source_path.stat()
    except OSError as exc:
        raise PocketTubeFormatError(f"Cannot read PocketTube export: {exc}") from exc
    if before.st_size > MAX_EXPORT_BYTES:
        raise PocketTubeFormatError(
            f"PocketTube export is larger than {MAX_EXPORT_BYTES} bytes"
        )
    try:
        content = source_path.read_bytes()
        after = source_path.stat()
    except OSError as exc:
        raise PocketTubeFormatError(f"Cannot read PocketTube export: {exc}") from exc
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise PocketTubeFormatError("PocketTube export changed while it was being read")
    return SourceDocument(
        path=source_path,
        name=source_path.name,
        mtime_ns=after.st_mtime_ns,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def extract_playlist_id(value: str) -> str | None:
    candidate = value.strip()
    if PLAYLIST_ID.fullmatch(candidate):
        return candidate
    parsed = urllib.parse.urlparse(candidate)
    values = urllib.parse.parse_qs(parsed.query).get("list") or []
    playlist_id = str(values[0]).strip() if values else ""
    return playlist_id if PLAYLIST_ID.fullmatch(playlist_id) else None


def _group_name(value: Any, label: str) -> str:
    name = str(value).strip()
    if not name:
        raise PocketTubeFormatError(f"{label} must not be empty")
    if len(name) > MAX_GROUP_NAME_LENGTH:
        raise PocketTubeFormatError(
            f"{label} exceeds {MAX_GROUP_NAME_LENGTH} characters"
        )
    return name


def parse_source(source: SourceDocument) -> PocketTubeSnapshot:
    try:
        export = json.loads(source.content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PocketTubeFormatError(f"Invalid PocketTube JSON: {exc}") from exc
    if not isinstance(export, dict):
        raise PocketTubeFormatError("PocketTube export must be a JSON object")

    group_lists: dict[str, list[Any]] = {}
    for raw_name, values in export.items():
        if isinstance(values, list):
            name = _group_name(raw_name, "Group name")
            group_lists[name] = values

    settings = export.get("ysc_settings") or {}
    if not isinstance(settings, dict):
        raise PocketTubeFormatError("ysc_settings must be an object when present")
    raw_sub_groups = settings.get("sub_groups") or {}
    if not isinstance(raw_sub_groups, dict):
        raise PocketTubeFormatError("ysc_settings.sub_groups must be an object")

    children_by_parent: dict[str, list[str]] = {}
    parent_by_child: dict[str, str] = {}
    ordered_names = list(group_lists)
    for raw_parent, raw_children in raw_sub_groups.items():
        parent = _group_name(raw_parent, "Parent group name")
        if not isinstance(raw_children, dict):
            raise PocketTubeFormatError(
                f"Sub-groups for {parent!r} must be an object"
            )
        if parent not in ordered_names:
            ordered_names.append(parent)
        children: list[str] = []
        for raw_child in raw_children:
            child = _group_name(raw_child, "Child group name")
            previous_parent = parent_by_child.get(child)
            if previous_parent is not None and previous_parent != parent:
                raise PocketTubeFormatError(
                    f"Group {child!r} has multiple parents: "
                    f"{previous_parent!r} and {parent!r}"
                )
            parent_by_child[child] = parent
            if child not in children:
                children.append(child)
            if child not in ordered_names:
                ordered_names.append(child)
        children_by_parent[parent] = children

    if len(ordered_names) > MAX_GROUPS:
        raise PocketTubeFormatError(f"Export contains more than {MAX_GROUPS} groups")

    visiting: set[str] = set()
    visited: set[str] = set()

    def validate_tree(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise PocketTubeFormatError(f"Group hierarchy contains a cycle at {name!r}")
        visiting.add(name)
        for child in children_by_parent.get(name, ()):
            validate_tree(child)
        visiting.remove(name)
        visited.add(name)

    for name in ordered_names:
        validate_tree(name)

    meta = export.get("ysc_meta") or {}
    if not isinstance(meta, dict):
        raise PocketTubeFormatError("ysc_meta must be an object when present")
    issues: list[ImportIssue] = []
    groups: list[GroupRecord] = []
    roots = [name for name in ordered_names if name not in parent_by_child]
    seen_groups: set[str] = set()

    def add_group(name: str, parent_key: str | None, position: int) -> None:
        if name in seen_groups:
            return
        seen_groups.add(name)
        raw_meta = meta.get(name) or {}
        if not isinstance(raw_meta, dict):
            issues.append(
                ImportIssue(
                    "warning",
                    "invalid_group_metadata",
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
                    "invalid_group_icon",
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
                    "truncated_group_icon",
                    name,
                    None,
                    "",
                    f"Group icon exceeded {MAX_ICON_LENGTH} characters",
                )
            )
        groups.append(GroupRecord(name, name, parent_key, position, icon))
        for child_position, child in enumerate(children_by_parent.get(name, ())):
            add_group(child, name, child_position)

    for root_position, root in enumerate(roots):
        add_group(root, None, root_position)

    if len(seen_groups) != len(ordered_names):
        missing = next(name for name in ordered_names if name not in seen_groups)
        raise PocketTubeFormatError(f"Group hierarchy is unreachable at {missing!r}")

    memberships: list[MembershipRecord] = []
    playlist_ids: set[str] = set()
    for group in groups:
        seen_playlist_ids: set[str] = set()
        for source_position, raw_value in enumerate(group_lists.get(group.key, ())):
            if len(memberships) >= MAX_MEMBERSHIPS:
                raise PocketTubeFormatError(
                    f"Export contains more than {MAX_MEMBERSHIPS} memberships"
                )
            if not isinstance(raw_value, str):
                issues.append(
                    ImportIssue(
                        "warning",
                        "non_text_playlist_reference",
                        group.key,
                        source_position,
                        "",
                        "Playlist reference is not text and was skipped",
                    )
                )
                continue
            playlist_id = extract_playlist_id(raw_value)
            if playlist_id is None:
                issues.append(
                    ImportIssue(
                        "warning",
                        "invalid_playlist_reference",
                        group.key,
                        source_position,
                        raw_value,
                        "Playlist reference does not contain a valid playlist ID",
                    )
                )
                continue
            if playlist_id in seen_playlist_ids:
                issues.append(
                    ImportIssue(
                        "warning",
                        "duplicate_group_membership",
                        group.key,
                        source_position,
                        raw_value,
                        "Duplicate playlist membership was skipped",
                    )
                )
                continue
            seen_playlist_ids.add(playlist_id)
            playlist_ids.add(playlist_id)
            memberships.append(
                MembershipRecord(group.key, playlist_id, source_position, raw_value)
            )

    return PocketTubeSnapshot(
        source=source,
        groups=tuple(groups),
        memberships=tuple(memberships),
        playlist_ids=frozenset(playlist_ids),
        issues=tuple(issues),
    )


def load_snapshot(path: Path) -> PocketTubeSnapshot:
    return parse_source(read_source(path))


def _start_import(conn: sqlite3.Connection, source: SourceDocument) -> int:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO import_runs(
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


def _fail_import(conn: sqlite3.Connection, import_id: int, error: str) -> None:
    with conn:
        conn.execute(
            """
            UPDATE import_runs
            SET status = 'failed', finished_at = ?, error = ?
            WHERE import_id = ?
            """,
            (utc_now(), str(error)[:10_000], import_id),
        )


def import_export(database_path: Path, export_path: Path) -> dict[str, Any]:
    initialize_database(database_path)
    source = read_source(export_path)
    conn = connect(database_path)
    import_id = _start_import(conn, source)
    try:
        snapshot = parse_source(source)
        with conn:
            conn.execute("DELETE FROM group_playlists")
            conn.execute("DELETE FROM groups")
            conn.execute("DELETE FROM playlist_references")
            conn.executemany(
                """
                INSERT INTO groups(
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
                INSERT INTO playlist_references(playlist_id, import_id)
                VALUES (?, ?)
                """,
                ((playlist_id, import_id) for playlist_id in sorted(snapshot.playlist_ids)),
            )
            conn.executemany(
                """
                INSERT INTO group_playlists(
                  group_key, playlist_id, position, source_value, import_id
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        membership.group_key,
                        membership.playlist_id,
                        membership.position,
                        membership.source_value,
                        import_id,
                    )
                    for membership in snapshot.memberships
                ),
            )
            conn.executemany(
                """
                INSERT INTO import_issues(
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
                UPDATE import_runs
                SET status = 'complete', finished_at = ?,
                    group_count = ?, membership_count = ?, playlist_count = ?,
                    issue_count = ?, error = ''
                WHERE import_id = ?
                """,
                (
                    utc_now(),
                    len(snapshot.groups),
                    len(snapshot.memberships),
                    len(snapshot.playlist_ids),
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
            "playlists": len(snapshot.playlist_ids),
            "issues": len(snapshot.issues),
        }
    except Exception as exc:
        _fail_import(conn, import_id, str(exc))
        raise
    finally:
        conn.close()
