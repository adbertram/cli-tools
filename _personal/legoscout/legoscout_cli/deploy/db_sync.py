"""Pull immutable run snapshots and ingest explicit observations on adam-server.

Crop transfers are additive and collision checked. Automatic crop deletion is
intentionally absent: a client snapshot cannot prove what the server references.
Code deployment is independent and never publishes a database file.
"""
from __future__ import annotations

import json
import shlex
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from ..ledger import db as ledger_db
from ..ledger import ingestion
from . import config, ssh


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
    """Read item semantics, independent of optional trailing attribute columns.

    openrsync emits nine columns; newer rsync adds trailing attributes. Directories
    are containers. Crop transfers must be regular files; reported symlinks and
    other special entries are rejected rather than silently omitted.
    """
    additions: list[str] = []
    collisions: list[str] = []
    for raw_line in output.splitlines():
        if not raw_line or "|" not in raw_line:
            continue
        item, relative = raw_line.split("|", 1)
        if len(item) < 4 or not relative or item[0] not in "><ch.":
            raise ValueError("unsupported crop rsync item: %s" % raw_line)
        if item[1] == "d":
            continue
        if item[1] != "f":
            raise ValueError("crop transfer requires a regular file: %s" % relative)
        attributes = item[2:]
        if item[0] in "><" and set(attributes) == {"+"}:
            additions.append(relative)
        elif item[2] == "c" or item[3] == "s":
            collisions.append(relative)
        elif item[0] != ".":
            raise ValueError("unsupported crop file transfer: %s" % raw_line)
    return additions, collisions


def _sync_additive(source: str, destination: str) -> dict[str, Any]:
    """Copy source-only files while refusing same-name content differences.

    ``--ignore-existing`` silently skips a destination entry that already has
    the same name -- including a symlink or directory planted where a crop
    belongs -- so every reported addition is re-checked afterwards and a
    non-regular destination collision blocks the leg loudly.
    """
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
    if not additions:
        return {"transferred": False, "collisions": []}
    # A directory creation item does not distinguish an absent container from
    # an existing symlink/file. Inspect destination types in reverse, dry-run
    # only: metadata is enough, and neither endpoint is changed by this check.
    destination_additions, destination_collisions = _parse_rsync_preflight(
        ssh.run_local([
            "rsync", "-a", "--existing", "--size-only", "--dry-run",
            "--itemize-changes", "--out-format=%i|%n", destination, source,
        ])
    )
    if destination_additions or destination_collisions:
        raise ValueError("crop destination collision: %s" % ", ".join(
            destination_additions + destination_collisions))
    ssh.run_local(
        [
            "rsync",
            "-a",
            "--ignore-existing",
            source,
            destination,
        ]
    )
    verified, collisions_after = _parse_rsync_preflight(
        ssh.run_local(
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
    )
    if collisions_after:
        raise ValueError(
            "crop content collision: %s" % ", ".join(collisions_after))
    if verified:
        raise ValueError(
            "crop transfer did not land (destination may hold a non-regular "
            "entry): %s" % ", ".join(verified))
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


def _pull_database(destination: str) -> dict[str, Any]:
    """Write a new immutable baseline; an existing local file is never replaced."""
    if Path(destination).exists() or Path(destination).is_symlink():
        raise FileExistsError("snapshot destination already exists: %s" % destination)
    remote_tmp = "/tmp/legoscout-pull-%s.db" % uuid.uuid4().hex
    program = "from legoscout_cli.ledger import db; import sys; db.snapshot(sys.argv[1], sys.argv[2])"
    ssh.run_remote([config.REMOTE_TOOL_PYTHON, "-c", program, config.REMOTE_SHARED_DB, remote_tmp])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            downloaded = str(Path(tmp) / "server.db")
            ssh.run_local(["scp", "-q", "%s:%s" % (config.REMOTE_HOST, remote_tmp), downloaded])
            ledger_db.snapshot(downloaded, destination, baseline=True)
    finally:
        ssh.run_remote(["rm", "-f", remote_tmp])
    return {"copied": True, "path": str(Path(destination).resolve()), "immutable": True}


def _ingest_database(payload: dict[str, Any]) -> dict[str, Any]:
    program = (
        "import json, sys; from legoscout_cli.ledger.ingestion import ingest; "
        "print(json.dumps(ingest(json.load(sys.stdin), path=sys.argv[1])))"
    )
    remote_command = shlex.join([config.REMOTE_TOOL_PYTHON, "-c", program, config.REMOTE_SHARED_DB])
    raw = ssh.run_local(["ssh", config.REMOTE_HOST, remote_command], input=json.dumps(payload, allow_nan=False))
    result = json.loads(raw)
    if (not isinstance(result, dict) or result.get("run_id") != payload["run_id"]
            or result.get("payload_hash") != ingestion.payload_hash(payload)):
        raise ValueError("server returned an invalid ingestion receipt")
    return result


def _outcome(action: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"ok": True, "result": action()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def pull(destination: str) -> dict[str, Any]:
    """Attempt immutable database and additive crop pulls independently."""
    database = _outcome(lambda: _pull_database(destination))
    crops = _outcome(_pull_crops)
    return {"ok": database["ok"] and crops["ok"], "db": database, "crops": crops}


def ingest(payload_path: str) -> dict[str, Any]:
    """Transfer crops before accepting their explicit, validated deal records."""
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    ingestion.validate_payload(payload)
    crops = _outcome(_push_crops)
    database = _outcome(lambda: _ingest_database(payload)) if crops["ok"] else {
        "ok": False, "skipped": True, "reason": "crop transfer must succeed before ingestion",
    }
    return {"ok": database["ok"] and crops["ok"], "db": database, "crops": crops}
