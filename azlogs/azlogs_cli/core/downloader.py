"""Kudu API: download logs from Azure Web App (stdlib only, no deps)."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def get_kudu_credentials(
    app_name: str, resource_group: str
) -> tuple[str, str]:
    """Get Kudu credentials via az CLI."""
    result = subprocess.run(
        [
            "az", "webapp", "deployment", "list-publishing-profiles",
            "--name", app_name,
            "--resource-group", resource_group,
            "--output", "json",
        ],
        capture_output=True, text=True, check=True,
    )
    profiles = json.loads(result.stdout)
    for profile in profiles:
        if profile.get("publishMethod") == "MSDeploy":
            return profile["userName"], profile["userPWD"]
    raise RuntimeError("No MSDeploy publishing profile found")


def build_kudu_url(app_name: str) -> str:
    """Build the Kudu SCM URL."""
    return f"https://{app_name}.scm.azurewebsites.net"


def kudu_request(url: str, username: str, password: str, timeout: int = 120) -> bytes:
    """Authenticated GET request to Kudu API."""
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = Request(url, headers={"Authorization": f"Basic {credentials}"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_kudu_dump(
    kudu_url: str, creds: tuple[str, str], output_dir: Path
) -> Path:
    """Download /api/dump → extract zip."""
    url = f"{kudu_url}/api/dump"
    print(f"  Fetching {url}...", file=sys.stderr)
    # Extended timeout — Kudu cold start can take 30+ seconds before dump begins
    data = kudu_request(url, *creds, timeout=300)
    zip_path = output_dir / "kudu-dump.zip"
    zip_path.write_bytes(data)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(output_dir)
    return zip_path


def download_kudu_zip(
    kudu_url: str, creds: tuple[str, str], vfs_path: str, output_dir: Path
) -> Path:
    """Download a directory as a single zip via /api/zip/ and extract it."""
    url = f"{kudu_url}/api/zip/{vfs_path}/"
    print(f"  Fetching {url}...", file=sys.stderr)
    # Extended timeout — large directories can take a few minutes
    data = kudu_request(url, *creds, timeout=300)
    zip_path = output_dir / "trace.zip"
    zip_path.write_bytes(data)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(output_dir)
    return zip_path


def list_vfs_directory(
    kudu_url: str, creds: tuple[str, str], vfs_path: str
) -> list[dict] | None:
    """GET VFS directory listing. Returns entries or None on error."""
    url = f"{kudu_url}/api/vfs/{vfs_path}/"
    try:
        data = kudu_request(url, *creds)
        result = json.loads(data)
        if isinstance(result, list):
            return result
    except (HTTPError, json.JSONDecodeError):
        pass
    return None


def download_vfs_file(
    kudu_url: str, creds: tuple[str, str], href: str, local_path: Path
) -> bool:
    """Download a single VFS file. Returns True on success."""
    try:
        data = kudu_request(href, *creds)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return True
    except HTTPError:
        return False


def download_vfs_recursive(
    kudu_url: str, creds: tuple[str, str], vfs_path: str, local_dir: Path
) -> list[Path]:
    """Recursively download a VFS directory."""
    downloaded: list[Path] = []
    entries = list_vfs_directory(kudu_url, creds, vfs_path)
    if entries is None:
        return downloaded

    for entry in entries:
        name = entry.get("name", "")
        href = entry.get("href", "")
        mime = entry.get("mime", "")

        if mime == "inode/directory":
            sub = download_vfs_recursive(
                kudu_url, creds, f"{vfs_path}/{name}", local_dir / name
            )
            downloaded.extend(sub)
        else:
            local_path = local_dir / name
            if download_vfs_file(kudu_url, creds, href, local_path):
                downloaded.append(local_path)

    return downloaded


def download_app_logs(
    kudu_url: str, creds: tuple[str, str], output_dir: Path
) -> list[Path]:
    """Download application log files (*.log) from LogFiles/ root via VFS."""
    entries = list_vfs_directory(kudu_url, creds, "LogFiles")
    if entries is None:
        return []

    downloaded = []
    for entry in entries:
        name = entry.get("name", "")
        # Skip directories and non-log files — docker logs are already in the dump
        if entry.get("mime") == "inode/directory":
            continue
        if not name.endswith(".log"):
            continue
        # Skip docker logs (already included in Kudu dump)
        if "_docker" in name:
            continue
        local = output_dir / "LogFiles" / name
        if download_vfs_file(kudu_url, creds, entry["href"], local):
            downloaded.append(local)
    return downloaded


def download_all(
    app_name: str, resource_group: str, output_dir: Path,
    include_kudu_trace: bool = False,
) -> Path:
    """Orchestrate full download: dump + VFS logs + optional trace overlay.

    The Kudu dump already includes LogFiles/kudu/trace/ files.
    Set include_kudu_trace=True to re-download them via /api/zip/ (overwrites
    dump copies with a fresh snapshot — useful if traces changed mid-download).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading logs to {output_dir}", file=sys.stderr)

    username, password = get_kudu_credentials(app_name, resource_group)
    kudu_url = build_kudu_url(app_name)
    print(f"Kudu URL: {kudu_url}", file=sys.stderr)

    # 1. Download Kudu dump (contains LogFiles/ with Docker logs + kudu trace)
    print("Downloading Kudu dump...", file=sys.stderr)
    download_kudu_dump(kudu_url, (username, password), output_dir)

    # 2. Optionally re-download Kudu trace logs (already included in dump)
    if include_kudu_trace:
        print("Downloading Kudu trace logs...", file=sys.stderr)
        trace_dir = output_dir / "LogFiles" / "kudu" / "trace"
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_zip = download_kudu_zip(
            kudu_url, (username, password), "LogFiles/kudu/trace", trace_dir
        )
        print(f"Downloaded trace logs ({trace_zip.stat().st_size} bytes)", file=sys.stderr)
    else:
        print("Skipping separate Kudu trace download (already in dump)", file=sys.stderr)

    # 3. Download application logs (any .log files not already in dump)
    print("Downloading application logs...", file=sys.stderr)
    app_logs = download_app_logs(kudu_url, (username, password), output_dir)
    if app_logs:
        for log in app_logs:
            print(f"  Downloaded {log.name}", file=sys.stderr)
    else:
        print("  No additional application logs found", file=sys.stderr)

    return output_dir
