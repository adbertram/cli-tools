"""SSH/SFTP helpers for pushing WordPress theme files."""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

from cli_tools_shared.exceptions import ClientError


STATUS_SCRIPT = """set -eu
remote_root=$1
theme=$2
remote_file=$3

root=${remote_root%/}
theme_dir="$root/wp-content/themes/$theme"
remote_path="$theme_dir/$remote_file"
remote_dir=$(dirname "$remote_path")

if command -v sha256sum >/dev/null 2>&1; then
  printf '%s\n' 'sha256sum_available=true'
  sha256sum_available=1
else
  printf '%s\n' 'sha256sum_available=false'
  sha256sum_available=0
fi

if [ -d "$theme_dir" ]; then
  printf '%s\n' 'theme_dir_exists=true'
else
  printf '%s\n' 'theme_dir_exists=false'
fi

if [ -d "$remote_dir" ]; then
  printf '%s\n' 'remote_dir_exists=true'
else
  printf '%s\n' 'remote_dir_exists=false'
fi

printf 'theme_dir=%s\n' "$theme_dir"
printf 'remote_dir=%s\n' "$remote_dir"
printf 'remote_path=%s\n' "$remote_path"

if [ -f "$remote_path" ]; then
  printf '%s\n' 'exists=true'
  bytes=$(wc -c < "$remote_path" | tr -d ' ')
  if [ "$sha256sum_available" = "1" ]; then
    sha=$(sha256sum "$remote_path" | awk '{print $1}')
  else
    sha=
  fi
  printf 'bytes=%s\n' "$bytes"
  printf 'sha256=%s\n' "$sha"
else
  printf '%s\n' 'exists=false'
  printf '%s\n' 'bytes='
  printf '%s\n' 'sha256='
fi
"""


APPLY_SCRIPT = """set -eu
remote_root=$1
theme=$2
remote_file=$3
temp_path=$4
backup_flag=$5
timestamp=$6

root=${remote_root%/}
theme_dir="$root/wp-content/themes/$theme"
remote_path="$theme_dir/$remote_file"
remote_dir=$(dirname "$remote_path")
backup_path=

if ! command -v sha256sum >/dev/null 2>&1; then
  printf '%s\n' 'ERROR: sha256sum is required for readback verification' >&2
  exit 12
fi

if [ ! -d "$theme_dir" ]; then
  printf 'ERROR: theme directory does not exist: %s\n' "$theme_dir" >&2
  exit 10
fi

if [ ! -d "$remote_dir" ]; then
  printf 'ERROR: remote destination directory does not exist: %s\n' "$remote_dir" >&2
  exit 11
fi

if [ ! -f "$temp_path" ]; then
  printf 'ERROR: uploaded temp file does not exist: %s\n' "$temp_path" >&2
  exit 13
fi

if [ "$backup_flag" = "1" ] && [ -f "$remote_path" ]; then
  backup_path="$remote_path.bak-$timestamp"
  cp -p "$remote_path" "$backup_path"
fi

mv "$temp_path" "$remote_path"
bytes=$(wc -c < "$remote_path" | tr -d ' ')
sha=$(sha256sum "$remote_path" | awk '{print $1}')

printf 'remote_path=%s\n' "$remote_path"
printf 'bytes=%s\n' "$bytes"
printf 'sha256=%s\n' "$sha"
printf 'backup_path=%s\n' "$backup_path"
"""


@dataclass(frozen=True)
class SshConfig:
    """Explicit SSH/SFTP connection settings."""

    host: str
    user: Optional[str] = None
    port: int = 22
    identity_file: Optional[Path] = None

    def destination(self) -> str:
        """Return the user@host destination accepted by ssh and sftp."""
        return f"{self.user}@{self.host}" if self.user else self.host

    def public_dict(self) -> dict:
        """Return connection metadata safe for command output."""
        return {
            "host": self.host,
            "user": self.user,
            "port": self.port,
            "identity_file_provided": self.identity_file is not None,
        }


def push_theme_file(
    *,
    theme: str,
    local_file: Path,
    remote_file: str,
    remote_root: str,
    host: str,
    user: Optional[str] = None,
    port: int = 22,
    identity_file: Optional[Path] = None,
    backup: bool = False,
    yes: bool = False,
    dry_run: bool = False,
) -> dict:
    """Push a local file into a remote classic WordPress theme directory."""
    if yes and dry_run:
        raise ValueError("--yes and --dry-run cannot be used together")

    source = _source_readback(local_file)
    normalized_theme = _validate_theme(theme)
    normalized_remote_file = _validate_remote_file(remote_file)
    normalized_remote_root = _validate_remote_root(remote_root)
    config = _validate_ssh_config(host, user, port, identity_file)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = _destination_paths(
        normalized_theme,
        normalized_remote_file,
        normalized_remote_root,
    )
    before = _remote_status(
        config,
        normalized_remote_root,
        normalized_theme,
        normalized_remote_file,
    )
    _assert_remote_ready(before)

    effective_dry_run = dry_run or not yes
    backup_preview = (
        f"{destination['remote_path']}.bak-{timestamp}"
        if backup and before["exists"]
        else None
    )

    result = {
        "action": "theme_file_push",
        "mode": "dry-run" if effective_dry_run else "applied",
        "mutated": False,
        "source": source,
        "connection": config.public_dict(),
        "destination": {
            **destination,
            "exists": before["exists"],
            "bytes": before["bytes"],
            "sha256": before["sha256"],
        },
        "backup": {
            "requested": backup,
            "would_create": bool(backup_preview) if effective_dry_run else False,
            "created": False,
            "path": backup_preview,
        },
        "confirmation_required": effective_dry_run and not yes,
    }

    if effective_dry_run:
        return result

    temp_path = _temporary_remote_path(destination["remote_path"], timestamp)
    _sftp_put(config, source["path"], temp_path)
    applied = _remote_apply(
        config,
        normalized_remote_root,
        normalized_theme,
        normalized_remote_file,
        temp_path,
        backup,
        timestamp,
    )

    matches_local = applied["sha256"] == source["sha256"] and applied["bytes"] == source["bytes"]
    if not matches_local:
        raise ClientError("Remote readback did not match the local source after upload")

    result["mutated"] = True
    result["destination"]["exists"] = True
    result["destination"]["bytes"] = applied["bytes"]
    result["destination"]["sha256"] = applied["sha256"]
    result["backup"]["would_create"] = False
    result["backup"]["created"] = bool(applied["backup_path"])
    result["backup"]["path"] = applied["backup_path"] or None
    result["readback"] = {
        "bytes": applied["bytes"],
        "sha256": applied["sha256"],
        "matches_local": True,
    }
    return result


def _source_readback(local_file: Path) -> dict:
    path = local_file.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Local file does not exist or is not a regular file: {local_file}")
    payload = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _validate_theme(theme: str) -> str:
    normalized = theme.strip()
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise ValueError("THEME must be a single theme directory name")
    return normalized


def _validate_remote_file(remote_file: str) -> str:
    normalized = remote_file.strip()
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("REMOTE_FILE must be a relative path inside the theme directory")
    return path.as_posix()


def _validate_remote_root(remote_root: str) -> str:
    normalized = remote_root.strip().rstrip("/")
    if not normalized or not normalized.startswith("/"):
        raise ValueError("--remote-root must be an absolute WordPress root path")
    return normalized


def _validate_ssh_config(
    host: str,
    user: Optional[str],
    port: int,
    identity_file: Optional[Path],
) -> SshConfig:
    normalized_host = host.strip()
    if not normalized_host:
        raise ValueError("--host is required")
    if port <= 0:
        raise ValueError("--port must be a positive integer")
    key_path = identity_file.expanduser().resolve() if identity_file else None
    if key_path is not None and not key_path.is_file():
        raise FileNotFoundError(f"SSH identity file does not exist: {identity_file}")
    normalized_user = user.strip() if user else None
    return SshConfig(
        host=normalized_host,
        user=normalized_user,
        port=port,
        identity_file=key_path,
    )


def _destination_paths(theme: str, remote_file: str, remote_root: str) -> dict:
    theme_dir = f"{remote_root}/wp-content/themes/{theme}"
    remote_path = f"{theme_dir}/{remote_file}"
    return {
        "remote_root": remote_root,
        "theme": theme,
        "remote_file": remote_file,
        "theme_dir": theme_dir,
        "remote_path": remote_path,
    }


def _assert_remote_ready(status: dict) -> None:
    if not status["sha256sum_available"]:
        raise ClientError("Remote host must provide sha256sum for readback verification")
    if not status["theme_dir_exists"]:
        raise ClientError(f"Remote theme directory does not exist: {status['theme_dir']}")
    if not status["remote_dir_exists"]:
        raise ClientError(f"Remote destination directory does not exist: {status['remote_dir']}")


def _remote_status(
    config: SshConfig,
    remote_root: str,
    theme: str,
    remote_file: str,
) -> dict:
    output = _run_ssh_script(
        config,
        STATUS_SCRIPT,
        [remote_root, theme, remote_file],
        failure_label="Remote destination readback failed",
    )
    parsed = _parse_key_value_output(output)
    required = {
        "sha256sum_available",
        "theme_dir_exists",
        "remote_dir_exists",
        "theme_dir",
        "remote_dir",
        "remote_path",
        "exists",
        "bytes",
        "sha256",
    }
    missing = sorted(required - parsed.keys())
    if missing:
        raise ClientError(f"Remote destination readback omitted: {', '.join(missing)}")

    remote_path = parsed["remote_path"]
    return {
        "sha256sum_available": parsed["sha256sum_available"] == "true",
        "theme_dir_exists": parsed["theme_dir_exists"] == "true",
        "remote_dir_exists": parsed["remote_dir_exists"] == "true",
        "theme_dir": parsed["theme_dir"],
        "remote_dir": parsed["remote_dir"],
        "remote_path": remote_path,
        "exists": parsed["exists"] == "true",
        "bytes": int(parsed["bytes"]) if parsed["bytes"] else None,
        "sha256": parsed["sha256"] or None,
    }


def _temporary_remote_path(remote_path: str, timestamp: str) -> str:
    path = PurePosixPath(remote_path)
    return f"{path.parent}/.{path.name}.cli-upload-{timestamp}-{os.getpid()}"


def _sftp_put(config: SshConfig, local_path: str, temp_path: str) -> None:
    batch = f"put {_quote_sftp_path(local_path)} {_quote_sftp_path(temp_path)}\n"
    result = subprocess.run(
        _sftp_command(config),
        input=batch,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown SFTP error"
        raise ClientError(f"SFTP upload failed: {message}")


def _remote_apply(
    config: SshConfig,
    remote_root: str,
    theme: str,
    remote_file: str,
    temp_path: str,
    backup: bool,
    timestamp: str,
) -> dict:
    output = _run_ssh_script(
        config,
        APPLY_SCRIPT,
        [remote_root, theme, remote_file, temp_path, "1" if backup else "0", timestamp],
        failure_label="Remote apply failed",
    )
    parsed = _parse_key_value_output(output)
    required = {"remote_path", "bytes", "sha256", "backup_path"}
    missing = sorted(required - parsed.keys())
    if missing:
        raise ClientError(f"Remote apply readback omitted: {', '.join(missing)}")
    return {
        "remote_path": parsed["remote_path"],
        "bytes": int(parsed["bytes"]),
        "sha256": parsed["sha256"],
        "backup_path": parsed["backup_path"],
    }


def _run_ssh_script(
    config: SshConfig,
    script: str,
    args: list[str],
    *,
    failure_label: str,
) -> str:
    remote_command = "sh -s -- " + " ".join(shlex.quote(arg) for arg in args)
    result = subprocess.run(
        _ssh_command(config, remote_command),
        input=script,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown SSH error"
        raise ClientError(f"{failure_label}: {message}")
    return result.stdout


def _ssh_command(config: SshConfig, remote_command: str) -> list[str]:
    command = ["ssh", "-p", str(config.port)]
    if config.identity_file is not None:
        command.extend(["-i", str(config.identity_file)])
    command.extend([config.destination(), remote_command])
    return command


def _sftp_command(config: SshConfig) -> list[str]:
    command = ["sftp", "-b", "-", "-P", str(config.port)]
    if config.identity_file is not None:
        command.extend(["-i", str(config.identity_file)])
    command.append(config.destination())
    return command


def _quote_sftp_path(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_key_value_output(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            continue
        if "=" not in line:
            raise ClientError(f"Unexpected remote readback line: {line}")
        key, value = line.split("=", 1)
        parsed[key] = value
    return parsed
