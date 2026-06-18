"""Read Dropbox desktop pending sync queue state from the local nucleus DB."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote


DEFAULT_DB_PATH = Path.home() / ".dropbox" / "instance1" / "sync" / "nucleus.sqlite3"
DEFAULT_DROPBOX_ROOT = Path.home() / "Dropbox"

_EXPECTED_COMMIT_COLUMNS = [("key", "BLOB"), ("value", "BLOB")]
_FILENAME_PATTERN = re.compile(
    rb"(?<![A-Za-z0-9_.@+() ])"
    rb"([A-Za-z0-9][A-Za-z0-9_.@+() -]{0,240}\.[A-Za-z0-9][A-Za-z0-9_.-]{0,20})"
    rb"(?![A-Za-z0-9_.@+() -])"
)
_PRINTABLE_PATTERN = re.compile(rb"[ -~]{4,}")


class SyncQueueError(Exception):
    """Raised when the Dropbox desktop queue cannot be read safely."""


def read_pending_sync_items(
    db_path: Path | str = DEFAULT_DB_PATH,
    dropbox_root: Path | str = DEFAULT_DROPBOX_ROOT,
    *,
    resolve_paths: bool = True,
) -> dict:
    """Return pending Dropbox desktop sync items from commit_intents."""
    database_path = Path(db_path).expanduser()
    if not database_path.is_file():
        raise SyncQueueError(f"Dropbox desktop sync DB not found: {database_path}")

    root_path = Path(dropbox_root).expanduser()
    with _connect_readonly(database_path) as conn:
        _verify_commit_intents_schema(conn)
        rows = conn.execute("SELECT key, value FROM commit_intents ORDER BY key").fetchall()

    entries = [_entry_from_row(key, value) for key, value in rows]
    filenames = {
        filename
        for entry in entries
        for filename in entry["filenames"]
    }
    path_candidates = _resolve_path_candidates(root_path, filenames) if resolve_paths else {}

    for entry in entries:
        candidates = []
        relative_candidates = []
        for filename in entry["filenames"]:
            for candidate in path_candidates.get(filename, []):
                candidates.append(str(candidate))
                relative_candidates.append(str(candidate.relative_to(root_path)))
        entry["path_candidates"] = candidates
        entry["dropbox_relative_path_candidates"] = relative_candidates
        entry["path_resolution"] = (
            "heuristic_filename_match" if candidates else "unresolved"
        )

    return {
        "database_path": str(database_path),
        "source_table": "commit_intents",
        "count": len(rows),
        "unique_filename_count": len(filenames),
        "path_resolution": {
            "attempted": resolve_paths,
            "heuristic": resolve_paths,
            "method": (
                "exact filename match under dropbox_root"
                if resolve_paths
                else "not attempted"
            ),
            "dropbox_root": str(root_path),
            "dropbox_root_exists": root_path.is_dir(),
            "candidate_paths_are_authoritative": False,
        },
        "entries": entries,
    }


def _connect_readonly(path: Path) -> sqlite3.Connection:
    quoted_path = quote(str(path), safe="/:")
    try:
        return sqlite3.connect(
            f"file:{quoted_path}?mode=ro&immutable=1",
            uri=True,
        )
    except sqlite3.Error as exc:
        raise SyncQueueError(f"Unable to open Dropbox desktop sync DB read-only: {path}") from exc


def _verify_commit_intents_schema(conn: sqlite3.Connection) -> None:
    columns = conn.execute("PRAGMA table_info(commit_intents)").fetchall()
    observed = [(row[1], row[2].upper()) for row in columns]
    if observed != _EXPECTED_COMMIT_COLUMNS:
        raise SyncQueueError(
            "Unexpected Dropbox sync DB schema for commit_intents: "
            f"expected key/value BLOB columns, got {observed or 'missing table'}"
        )


def _entry_from_row(key: bytes, value: bytes) -> dict:
    filenames = _extract_filenames(value)
    return {
        "queue_key_hex": key.hex(),
        "value_sha256": hashlib.sha256(value).hexdigest(),
        "filenames": filenames,
        "filename": filenames[0] if filenames else None,
        "payload_strings": _extract_printable_strings(value),
    }


def _extract_filenames(blob: bytes) -> list[str]:
    names = []
    seen = set()
    for match in _FILENAME_PATTERN.finditer(blob):
        name = match.group(1).decode("utf-8", "replace")
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _extract_printable_strings(blob: bytes) -> list[str]:
    return [
        match.group(0).decode("utf-8", "replace")
        for match in _PRINTABLE_PATTERN.finditer(blob)
    ]


def _resolve_path_candidates(root: Path, filenames: set[str]) -> dict[str, list[Path]]:
    if not filenames or not root.is_dir():
        return {}

    matches = {filename: [] for filename in filenames}
    for dirpath, dirnames, file_names in os.walk(root):
        dirnames[:] = [name for name in dirnames if not _is_ignored_dir(name)]
        matching_names = filenames.intersection(file_names)
        if not matching_names:
            continue
        directory = Path(dirpath)
        for name in sorted(matching_names):
            matches[name].append(directory / name)

    return {
        name: sorted(paths, key=lambda path: str(path))
        for name, paths in matches.items()
    }


def _is_ignored_dir(name: str) -> bool:
    return name in {".dropbox.cache", ".git", "__pycache__"}
