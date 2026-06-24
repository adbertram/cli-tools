"""Thin wrapper around the official Descript API CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable, Optional

from cli_tools_shared.config import get_tool_data_dir


OFFICIAL_CLI_PACKAGE = "@descript/platform-cli@latest"
OFFICIAL_CLI_BINARY = "descript-api"
NPM_BINARY = "npm"


class PlatformCLIError(Exception):
    """Raised when the official Descript API CLI cannot complete a command."""


def _platform_install_dir() -> Path:
    configured = os.environ.get("DESCRIPT_API_CLI_INSTALL_DIR")
    if configured:
        return Path(configured).expanduser()

    return get_tool_data_dir("descript") / "platform-cli"


def _platform_install_executable() -> Path:
    return _platform_install_dir() / "node_modules" / ".bin" / OFFICIAL_CLI_BINARY


def _install_platform_cli() -> str:
    npm = shutil.which(NPM_BINARY)
    if not npm:
        raise PlatformCLIError(
            "npm is required to install the official Descript API CLI package "
            f"{OFFICIAL_CLI_PACKAGE}."
        )

    install_dir = _platform_install_dir()
    install_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [npm, "install", "--prefix", str(install_dir), OFFICIAL_CLI_PACKAGE],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise PlatformCLIError(
            "Failed to install the official Descript API CLI package "
            f"{OFFICIAL_CLI_PACKAGE}: {detail}"
        )

    executable = _platform_install_executable()
    if not executable.exists():
        raise PlatformCLIError(
            "Official Descript API CLI package installed, but the "
            f"{OFFICIAL_CLI_BINARY} binary was not found at {executable}."
        )
    return str(executable)


def _platform_executable() -> str:
    configured = os.environ.get("DESCRIPT_API_CLI")
    if configured:
        return configured

    executable = shutil.which(OFFICIAL_CLI_BINARY)
    if executable:
        return executable

    installed = _platform_install_executable()
    if installed.exists():
        return str(installed)

    return _install_platform_cli()


def platform_executable_path() -> str:
    """Return the executable path, provisioning the official CLI if needed."""
    return _platform_executable()


def run_platform(
    args: Iterable[str],
    *,
    capture_output: bool = False,
    check: bool = True,
    profile: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    """Run the official `descript-api` CLI."""
    command = [_platform_executable(), *[str(arg) for arg in args]]
    env = os.environ.copy()
    if profile:
        env["DESCRIPT_PROFILE"] = profile
    result = subprocess.run(
        command,
        capture_output=capture_output,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        detail = ""
        if capture_output:
            detail = (result.stderr or result.stdout or "").strip()
        raise PlatformCLIError(
            detail or f"{OFFICIAL_CLI_BINARY} exited with status {result.returncode}"
        )
    return result


def run_platform_passthrough(args: Iterable[str], *, profile: Optional[str] = None) -> int:
    """Run the official CLI with inherited stdout/stderr."""
    return run_platform(args, check=False, profile=profile).returncode


def run_platform_json(args: Iterable[str], *, profile: Optional[str] = None) -> dict | list:
    """Run an official CLI command that supports `--json` and parse stdout."""
    result = run_platform(args, capture_output=True, profile=profile)
    stdout = result.stdout.strip()
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PlatformCLIError(
            f"Expected JSON from {OFFICIAL_CLI_BINARY}, received: {stdout[:500]}"
        ) from exc


def _append_option(args: list[str], flag: str, value: Optional[str]) -> None:
    if value is not None:
        args.extend([flag, str(value)])


def _append_bool(args: list[str], flag: str, enabled: bool) -> None:
    if enabled:
        args.append(flag)


def _append_repeated(args: list[str], flag: str, values: Optional[list[str]]) -> None:
    for value in values or []:
        args.extend([flag, str(value)])


def list_projects_json(
    *,
    limit: int = 20,
    name: Optional[str] = None,
    folder_path: Optional[str] = None,
    created_by: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
    sort: Optional[str] = None,
    direction: Optional[str] = None,
    cursor: Optional[str] = None,
) -> list[dict]:
    args = ["list-projects", "--json", "--no-interactive", "--limit", str(limit)]
    _append_option(args, "--name", name)
    _append_option(args, "--folder-path", folder_path)
    _append_option(args, "--created-by", created_by)
    _append_option(args, "--created-after", created_after)
    _append_option(args, "--created-before", created_before)
    _append_option(args, "--updated-after", updated_after)
    _append_option(args, "--updated-before", updated_before)
    _append_option(args, "--sort", sort)
    _append_option(args, "--direction", direction)
    _append_option(args, "--cursor", cursor)
    payload = run_platform_json(args)
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    if isinstance(payload, list):
        return payload
    raise PlatformCLIError("Unexpected project list response from descript-api.")


def get_project_json(project_id: str) -> dict:
    payload = run_platform_json(["get-project", "--json", project_id])
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    if isinstance(payload, dict):
        return payload
    raise PlatformCLIError("Unexpected project response from descript-api.")


def list_compositions_json(project_id: str) -> list[dict]:
    project = get_project_json(project_id)
    compositions = project.get("compositions")
    if isinstance(compositions, list):
        return compositions
    raise PlatformCLIError("descript-api project response did not include a compositions list.")


def list_media_files_json(project_id: str) -> list[dict]:
    project = get_project_json(project_id)
    media_files = project.get("media_files")
    if isinstance(media_files, dict):
        return [
            {"path": path, **(value if isinstance(value, dict) else {"value": value})}
            for path, value in media_files.items()
        ]
    if isinstance(media_files, list):
        return media_files
    return []


def select_properties(records: list[dict], properties: Optional[str]) -> list[dict]:
    if not properties:
        return records
    selected = [prop.strip() for prop in properties.split(",") if prop.strip()]
    return [
        {prop: resolve_property(record, prop) for prop in selected}
        for record in records
    ]


def select_object_properties(record: dict, properties: Optional[str]) -> dict:
    if not properties:
        return record
    selected = [prop.strip() for prop in properties.split(",") if prop.strip()]
    return {prop: resolve_property(record, prop) for prop in selected}


def resolve_property(data: dict, prop: str):
    """Resolve a property path like `owner.email` from a nested dict."""
    current = data
    for part in prop.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def official_config_validate() -> dict:
    try:
        result = run_platform(["config", "validate"], capture_output=True, check=False)
    except PlatformCLIError as exc:
        return {"api_test": f"failed: {exc}"}
    if result.returncode == 0:
        return {"api_test": "passed"}
    detail = (result.stderr or result.stdout or "").strip()
    return {"api_test": f"failed: {detail or 'descript-api config validate failed'}"}
