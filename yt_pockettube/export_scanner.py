"""Discover previously unseen PocketTube exports in a local directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .database import connect
from .importers import PocketTubeFormatError, SourceDocument, read_source


ExportKind = Literal["playlist", "subscription"]


@dataclass(frozen=True)
class ExportCandidate:
    kind: ExportKind
    source: SourceDocument


@dataclass(frozen=True)
class ExportScan:
    candidates: tuple[ExportCandidate, ...]
    errors: tuple[tuple[str, str], ...]
    ignored: int
    already_imported: int


def classify_export(path: Path) -> ExportKind | None:
    name = path.name.casefold()
    if path.suffix.casefold() != ".json":
        return None
    if "subscription_manager" in name:
        return "subscription"
    if "playlist_manager" in name:
        return "playlist"
    return None


def _seen_hashes(database_path: Path, kind: ExportKind) -> set[str]:
    if not database_path.is_file():
        return set()
    table = "import_runs" if kind == "playlist" else "subscription_import_runs"
    conn = connect(database_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            return set()
        return {
            str(row["source_sha256"])
            for row in conn.execute(
                f"SELECT DISTINCT source_sha256 FROM {table} "
                "WHERE status = 'complete' AND source_sha256 <> ''"
            )
        }
    finally:
        conn.close()


def scan_exports(database_path: Path, exports_directory: Path) -> ExportScan:
    directory = Path(exports_directory).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"PocketTube exports directory not found: {directory}")

    seen = {
        "playlist": _seen_hashes(database_path, "playlist"),
        "subscription": _seen_hashes(database_path, "subscription"),
    }
    candidates: list[ExportCandidate] = []
    errors: list[tuple[str, str]] = []
    ignored = 0
    already_imported = 0
    for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.casefold() != ".json":
            continue
        kind = classify_export(path)
        if kind is None:
            ignored += 1
            continue
        try:
            source = read_source(path)
        except (OSError, PocketTubeFormatError) as exc:
            message = str(exc).replace(str(path.resolve()), path.name)
            errors.append((path.name, message))
            continue
        if source.sha256 in seen[kind]:
            already_imported += 1
            continue
        candidates.append(ExportCandidate(kind=kind, source=source))
        seen[kind].add(source.sha256)

    candidates.sort(
        key=lambda candidate: (
            candidate.kind,
            candidate.source.mtime_ns,
            candidate.source.name.casefold(),
        )
    )
    return ExportScan(
        candidates=tuple(candidates),
        errors=tuple(errors),
        ignored=ignored,
        already_imported=already_imported,
    )
