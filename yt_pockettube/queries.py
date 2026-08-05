"""Read-only PocketTube catalog projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .database import connect


MAX_PROJECTED_GROUPS = 10_000
MAX_PROJECTED_MEMBERSHIPS = 250_000


def playlist_group_projection(database_path: Path) -> dict[str, Any]:
    conn = connect(database_path)
    try:
        counts = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM groups) AS groups,
              (SELECT COUNT(*) FROM group_playlists) AS memberships
            """
        ).fetchone()
        group_count = int(counts["groups"])
        membership_count = int(counts["memberships"])
        if group_count > MAX_PROJECTED_GROUPS:
            raise RuntimeError(
                f"PocketTube catalog has more than {MAX_PROJECTED_GROUPS} groups"
            )
        if membership_count > MAX_PROJECTED_MEMBERSHIPS:
            raise RuntimeError(
                "PocketTube catalog has more than "
                f"{MAX_PROJECTED_MEMBERSHIPS} memberships"
            )
        source = conn.execute(
            """
            SELECT import_id, source_sha256
            FROM import_runs
            WHERE status = 'complete'
            ORDER BY import_id DESC
            LIMIT 1
            """
        ).fetchone()
        if source is None:
            raise RuntimeError("PocketTube catalog has no successful import")
        groups = [
            dict(row)
            for row in conn.execute(
                """
                SELECT group_key, name, parent_key, position, icon
                FROM groups
                ORDER BY CASE WHEN parent_key IS NULL THEN 0 ELSE 1 END,
                         COALESCE(parent_key, ''), position, group_key
                """
            )
        ]
        memberships = [
            dict(row)
            for row in conn.execute(
                """
                SELECT group_key, playlist_id, position
                FROM group_playlists
                ORDER BY group_key, position, playlist_id
                """
            )
        ]
        return {
            "revision": f"{source['import_id']}:{source['source_sha256']}",
            "groups": groups,
            "memberships": memberships,
        }
    finally:
        conn.close()
