"""Independently sync the live ledger and shared minifigure crops.

Database copies retain the original SQLite online-backup behavior so WAL pages
are included. Crops have their own additive rsync leg: existing relative names
are never overwritten, and a checksum mismatch blocks that leg loudly. Public
``pull``/``push`` return an outcome for each leg so one failure cannot hide the
other.

Retention runs only after both push legs succeed. It builds references through
the canonical ledger/minifig-analysis readers before it inventories or removes
anything remotely, then applies strict age, fraction, and count guards.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import shlex
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator

from ..ledger import db as ledger_db
from ..ledger import minifig_analysis
from . import config, ssh


_RETENTION_AGE_SECONDS = 30 * 24 * 60 * 60
_MAX_RETENTION_FILES = 1000


def _with_trailing_slash(value: str) -> str:
    return value.rstrip("/") + "/"


def _remote_crop_source() -> str:
    return "%s:%s" % (
        config.REMOTE_HOST,
        _with_trailing_slash(config.REMOTE_SHARED_CROPS),
    )


def _local_crop_source() -> str:
    return _with_trailing_slash(config.LOCAL_SHARED_CROPS)


def _ensure_remote_crop_root() -> None:
    ssh.run_remote_script(
        "mkdir -p %s\n" % shlex.quote(config.REMOTE_SHARED_CROPS)
    )


def _parse_rsync_preflight(output: str) -> tuple[list[str], list[str]]:
    additions: list[str] = []
    collisions: list[str] = []
    for raw_line in output.splitlines():
        if not raw_line or "|" not in raw_line:
            continue
        item, relative = raw_line.split("|", 1)
        if len(item) < 11 or item[1] != "f":
            continue
        if item[0] == ">" and item[2:] == "+" * 9:
            additions.append(relative)
            continue
        if item[0] == ">" and (item[2] == "c" or item[3] == "s"):
            collisions.append(relative)
    return additions, collisions


def _sync_additive(source: str, destination: str) -> dict[str, Any]:
    """Copy source-only files while refusing same-name content differences."""
    preflight = ssh.run_local(
        [
            "rsync",
            "-a",
            "--checksum",
            "--dry-run",
            "--itemize-changes",
            "--out-format=%i|%n",
            source,
            destination,
        ]
    )
    additions, collisions = _parse_rsync_preflight(preflight)
    if collisions:
        raise ValueError("crop content collision: %s" % ", ".join(collisions))
    ssh.run_local(
        [
            "rsync",
            "-a",
            "--ignore-existing",
            source,
            destination,
        ]
    )
    return {"transferred": bool(additions), "collisions": []}


def _pull_crops() -> dict[str, Any]:
    """Merge remote-authoritative crop files into the local shared root."""
    Path(config.LOCAL_SHARED_CROPS).mkdir(parents=True, exist_ok=True)
    _ensure_remote_crop_root()
    return _sync_additive(_remote_crop_source(), _local_crop_source())


def _push_crops() -> dict[str, Any]:
    """Add local crop files to the remote shared root without overwrites."""
    Path(config.LOCAL_SHARED_CROPS).mkdir(parents=True, exist_ok=True)
    _ensure_remote_crop_root()
    return _sync_additive(_local_crop_source(), _remote_crop_source())


def _pull_database() -> dict[str, bool]:
    """Snapshot adam-server's shared ledger down to the local working copy."""
    remote_tmp = "/tmp/legoscout-pull-%d.db" % os.getpid()
    ssh.run_remote_script(
        "set -euo pipefail\n"
        "sqlite3 %s '.backup %s'\n"
        % (shlex.quote(config.REMOTE_SHARED_DB), shlex.quote(remote_tmp))
    )
    try:
        ssh.run_local(
            [
                "scp",
                "-q",
                "%s:%s" % (config.REMOTE_HOST, remote_tmp),
                config.LOCAL_DB,
            ]
        )
    finally:
        ssh.run_remote_script("rm -f %s\n" % shlex.quote(remote_tmp))
    return {"copied": True}


def _push_database(snapshot_path: str | None = None) -> dict[str, bool]:
    """Snapshot the local working copy up to adam-server's shared ledger."""
    if snapshot_path is None:
        with tempfile.TemporaryDirectory() as tmp:
            return _push_database(os.path.join(tmp, "found_deals.db"))

    ssh.run_local(
        ["sqlite3", config.LOCAL_DB, ".backup %s" % snapshot_path]
    )
    remote_tmp = "/tmp/legoscout-push-%d.db" % os.getpid()
    ssh.run_local(
        [
            "scp",
            "-q",
            snapshot_path,
            "%s:%s" % (config.REMOTE_HOST, remote_tmp),
        ]
    )
    # Same-filesystem replacement is atomic, so the display never opens a
    # partially copied ledger.
    ssh.run_remote_script(
        "set -euo pipefail\n"
        "mkdir -p %s\n"
        "mv %s %s\n"
        % (
            shlex.quote(config.REMOTE_SHARED_DIR),
            shlex.quote(remote_tmp),
            shlex.quote(config.REMOTE_SHARED_DB),
        )
    )
    return {"copied": True}


def _relative_ref(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("crop ref must be a non-empty POSIX relative path")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or ".." in parsed.parts
        or value != parsed.as_posix()
    ):
        raise ValueError("unsafe crop ref: %r" % value)
    return value


def referenced_crop_refs(path: str) -> set[str]:
    """Build the authoritative crop-reference set from one ledger snapshot."""
    refs: set[str] = set()
    for index, record in enumerate(ledger_db.load_deals(path)):
        label = record.get("listing_key") or "row %d" % index
        raw = record.get("minifig_analysis")
        if raw is None or raw == []:
            continue
        try:
            analysis = minifig_analysis.entries(record)
            errors = [
                "entry %d: %s" % (entry_index, error)
                for entry_index, entry in enumerate(analysis)
                for error in minifig_analysis.entry_errors(entry)
            ]
            errors.extend(minifig_analysis.batch_errors(analysis))
            if errors:
                raise ValueError("; ".join(errors))
            record_refs = minifig_analysis.crop_refs(analysis)
            record_refs.extend(
                detection["crop_ref"]
                for entry in analysis
                for detection in entry.get("detections") or []
            )
            for ref in record_refs:
                refs.add(_relative_ref(ref))
        except (minifig_analysis.Unreadable, ValueError) as exc:
            raise ValueError(
                "%s minifig_analysis is unreadable: %s" % (label, exc)
            ) from exc
    return refs


_REMOTE_INVENTORY_PROGRAM = r'''import json
import os
import stat
import sys

root = os.path.abspath(sys.argv[1])
if os.path.islink(root):
    raise RuntimeError("crop root must not be a symlink")
rows = []
for current, directories, files in os.walk(root, followlinks=False):
    directories[:] = [
        name for name in directories
        if not os.path.islink(os.path.join(current, name))
    ]
    for name in files:
        full = os.path.join(current, name)
        if os.path.islink(full):
            continue
        info = os.stat(full, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            continue
        rows.append({
            "path": os.path.relpath(full, root).replace(os.sep, "/"),
            "mtime": info.st_mtime,
        })
rows.sort(key=lambda item: item["path"])
print(json.dumps(rows, separators=(",", ":")))
'''


def _remote_inventory() -> list[dict[str, Any]]:
    script = (
        "set -euo pipefail\n"
        "mkdir -p %s\n"
        "%s - %s <<'PY'\n"
        % (
            shlex.quote(config.REMOTE_SHARED_CROPS),
            shlex.quote(config.REMOTE_TOOL_PYTHON),
            shlex.quote(config.REMOTE_SHARED_CROPS),
        )
        + _REMOTE_INVENTORY_PROGRAM
        + "PY\n"
    )
    raw = ssh.run_remote_script(script)
    try:
        inventory = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("remote crop inventory returned malformed JSON") from exc
    if not isinstance(inventory, list):
        raise ValueError("remote crop inventory must be an array")
    return inventory


def retention_candidates(
    inventory: list[dict[str, Any]],
    referenced: set[str],
    *,
    now: float | None = None,
) -> list[str]:
    """Select old unreferenced files, then enforce both deletion guards."""
    checked_refs = {_relative_ref(ref) for ref in referenced}
    checked: list[tuple[str, float]] = []
    seen: set[str] = set()
    for item in inventory:
        if not isinstance(item, dict):
            raise ValueError("remote crop inventory entry must be an object")
        path = _relative_ref(item.get("path"))
        mtime = item.get("mtime")
        if (
            not isinstance(mtime, (int, float))
            or isinstance(mtime, bool)
            or not math.isfinite(mtime)
        ):
            raise ValueError("remote crop inventory mtime is invalid for %s" % path)
        if path in seen:
            raise ValueError("duplicate remote crop inventory path: %s" % path)
        seen.add(path)
        checked.append((path, float(mtime)))

    cutoff = (time.time() if now is None else now) - _RETENTION_AGE_SECONDS
    candidates = sorted(
        path
        for path, mtime in checked
        if path not in checked_refs and mtime < cutoff
    )
    if len(candidates) > _MAX_RETENTION_FILES:
        raise ValueError(
            "retention blocked: %s files exceeds 1,000-file limit"
            % format(len(candidates), ",")
        )
    if checked and len(candidates) * 4 > len(checked):
        raise ValueError(
            "retention blocked: deleting %d of %d files exceeds 25%%"
            % (len(candidates), len(checked))
        )
    return candidates


_REMOTE_DELETE_PROGRAM = r'''import json
import os
import stat
import sys
from pathlib import PurePosixPath

root = os.path.abspath(sys.argv[1])
if os.path.islink(root):
    raise RuntimeError("crop root must not be a symlink")
candidates = json.loads(__CANDIDATES__)
targets = []
for relative in candidates:
    parts = PurePosixPath(relative).parts
    current = root
    for part in parts:
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise RuntimeError("refusing symlink path: " + relative)
    resolved = os.path.realpath(current)
    if os.path.commonpath([root, resolved]) != root:
        raise RuntimeError("refusing escaped path: " + relative)
    info = os.stat(current, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("refusing non-file path: " + relative)
    targets.append((relative, current))
for relative, target in targets:
    os.unlink(target)
print(json.dumps([relative for relative, _target in targets], separators=(",", ":")))
'''


def _delete_remote_candidates(candidates: list[str]) -> list[str]:
    checked = [_relative_ref(path) for path in candidates]
    payload = json.dumps(checked, separators=(",", ":"))
    program = _REMOTE_DELETE_PROGRAM.replace(
        "__CANDIDATES__", json.dumps(payload)
    )
    script = (
        "set -euo pipefail\n"
        "%s - %s <<'PY'\n"
        % (
            shlex.quote(config.REMOTE_TOOL_PYTHON),
            shlex.quote(config.REMOTE_SHARED_CROPS),
        )
        + program
        + "PY\n"
    )
    raw = ssh.run_remote_script(script)
    try:
        deleted = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("remote crop deletion returned malformed JSON") from exc
    if deleted != checked:
        raise ValueError("remote crop deletion result did not match candidates")
    return deleted


def _retention(
    snapshot_path: str | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    references = referenced_crop_refs(
        config.LOCAL_DB if snapshot_path is None else snapshot_path
    )
    inventory = _remote_inventory()
    candidates = retention_candidates(inventory, references, now=now)
    deleted = _delete_remote_candidates(candidates) if candidates else []
    return {
        "scanned": len(inventory),
        "referenced": len(references),
        "deleted": deleted,
    }


def _outcome(action: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"ok": True, "result": action()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def pull() -> dict[str, Any]:
    """Attempt database and crop pulls independently and report both."""
    database = _outcome(_pull_database)
    crops = _outcome(_pull_crops)
    return {
        "ok": database["ok"] and crops["ok"],
        "db": database,
        "crops": crops,
    }


@contextmanager
def _push_lock() -> Iterator[None]:
    """Serialize remote DB installation through crop retention."""
    with open(config.LOCAL_DB + ".push.lock", "a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _skipped_retention() -> dict[str, Any]:
    return {
        "ok": False,
        "skipped": True,
        "reason": "database and crop push must both succeed",
    }


def push() -> dict[str, Any]:
    """Attempt both push legs; retain against the installed DB snapshot."""
    with _push_lock():
        try:
            snapshot_context = tempfile.TemporaryDirectory()
        except Exception as exc:
            database = {"ok": False, "error": str(exc)}
            crops = _outcome(_push_crops)
            retention = _skipped_retention()
        else:
            with snapshot_context as tmp:
                snapshot_path = os.path.join(tmp, "found_deals.db")
                database = _outcome(lambda: _push_database(snapshot_path))
                crops = _outcome(_push_crops)
                if database["ok"] and crops["ok"]:
                    retention = _outcome(lambda: _retention(snapshot_path))
                else:
                    retention = _skipped_retention()
        return {
            "ok": database["ok"] and crops["ok"] and retention["ok"],
            "db": database,
            "crops": crops,
            "retention": retention,
        }
