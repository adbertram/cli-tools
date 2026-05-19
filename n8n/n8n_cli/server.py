"""Centralized server execution module.

Provides a single interface for running commands on the n8n server, whether
the CLI is running locally on the server or remotely via SSH.

Local mode is activated when SSH_HOST is "localhost" or "127.0.0.1", or when
no SSH_HOST is set and BASE_URL points to localhost.
"""
import os
import subprocess
from urllib.parse import urlparse

from .n8n_api import N8nApiError


def get_server_host() -> str:
    """Get SSH host from .env (SSH_HOST) or derive from BASE_URL."""
    ssh_host = os.environ.get("SSH_HOST")
    if ssh_host:
        return ssh_host

    base = os.environ.get("BASE_URL", "")
    if base:
        parsed = urlparse(base)
        return parsed.hostname or "localhost"

    raise N8nApiError("Cannot determine SSH host. Set SSH_HOST in .env")


def is_local() -> bool:
    """Check if the CLI is running on the n8n server (no SSH needed).

    Returns True when SSH_HOST is localhost/127.0.0.1, or when no SSH_HOST
    is set and BASE_URL points to localhost/127.0.0.1.
    """
    host = get_server_host()
    return host in ("localhost", "127.0.0.1")


def run_on_server(command: str, timeout: int = 30) -> str:
    """Run a command on the n8n server, returning stdout.

    Uses a local shell when running on the server, SSH otherwise.
    Raises RuntimeError on non-zero exit code.
    """
    if is_local():
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True, timeout=timeout,
        )
    else:
        host = get_server_host()
        result = subprocess.run(
            ["ssh", host, command],
            capture_output=True, text=True, timeout=timeout,
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed (exit {result.returncode}): {stderr}")
    return result.stdout


def run_on_server_raw(command: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a command on the n8n server, returning the raw CompletedProcess.

    Uses a local shell when running on the server, SSH otherwise.
    Callers are responsible for checking returncode.
    """
    if is_local():
        return subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True, timeout=timeout,
        )
    else:
        host = get_server_host()
        return subprocess.run(
            ["ssh", host, command],
            capture_output=True, text=True, timeout=timeout,
        )


def sync_to_server(src: str, dest: str, excludes: list[str] = None) -> subprocess.CompletedProcess:
    """Rsync a directory to the server.

    Local mode: rsync between local paths.
    Remote mode: rsync to host:dest.
    """
    cmd = ["rsync", "-az", "--delete"]
    for exc in (excludes or []):
        cmd.extend(["--exclude", exc])

    if is_local():
        cmd.extend([f"{src}/", f"{dest}/"])
    else:
        host = get_server_host()
        cmd.extend([f"{src}/", f"{host}:{dest}/"])

    return subprocess.run(cmd, capture_output=True, text=True)


def copy_file_to_server(src: str, dest: str) -> subprocess.CompletedProcess:
    """Copy a single file to the server.

    Local mode: cp.
    Remote mode: scp.
    """
    if is_local():
        return subprocess.run(["cp", src, dest], capture_output=True, text=True)
    else:
        host = get_server_host()
        return subprocess.run(["scp", src, f"{host}:{dest}"], capture_output=True, text=True)
