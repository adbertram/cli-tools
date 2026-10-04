"""Server commands - manage the n8n server instance."""
import json
import typer

from ..n8n_api import N8nApiError
from cli_tools_shared.output import command, print_json, print_error, print_info, print_success
from ..server import restart_n8n, run_on_server, run_on_server_raw
from . import logs, server_config

app = typer.Typer(help="Manage the n8n server", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "config": [
        "api_key"
    ],
    "logs": [
        "api_key"
    ],
    "restart": [
        "api_key"
    ],
    "upgrade": [
        "api_key"
    ],
    "version": [
        "api_key"
    ],
    "deploy-browser-session": ["api_key"],
}

# Register logs as a sub-group: n8n server logs ...
app.add_typer(logs.app, name="logs", help="Query n8n server logs and configuration")
app.add_typer(server_config.app, name="config", help="Manage n8n server configuration")

N8N_BIN = "/usr/local/lib/node_modules/n8n/bin/n8n"
N8N_INSTALL_PREFIX = "/usr/local"


@app.command("deploy-browser-session")
@command
def deploy_browser_session(
    tool: str = typer.Argument(..., help="Installed owning service CLI"),
    browser_profile: str = typer.Option(..., "--browser-profile", help="Explicit named service browser profile"),
    expected_account_id: str = typer.Option(..., "--expected-account-id", help="Exact verified service account ID"),
    expected_username: str = typer.Option(None, "--expected-username", help="Expected service account username"),
):
    """Transfer a private service session to a new inactive server profile.

    Both service CLIs and required nonsecret root configuration must already
    be deployed. Existing destination profiles are never replaced. The remote
    owning CLI verifies exact identity before and after atomic publication.
    """
    import os
    import re
    import shlex
    import stat
    import subprocess
    import tempfile
    from pathlib import Path
    from cli_tools_shared.auth import PORTABLE_SESSION_MAX_BYTES, read_session_bundle, validate_session_profile
    from cli_tools_shared.config import get_tool_data_dir

    validate_session_profile(browser_profile)
    for value in (tool, expected_account_id, expected_username):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", value):
            raise ValueError("Invalid portable session tool or expected identity")
    executable = Path.home() / ".local" / "bin" / tool
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("Owning local service CLI is not installed")
    transfers = get_tool_data_dir("n8n") / "session-transfers"
    transfers.mkdir(mode=0o700, parents=True, exist_ok=True)
    if transfers.absolute() != transfers.resolve() or transfers.stat().st_uid != os.getuid() or stat.S_IMODE(transfers.stat().st_mode) & 0o077:
        raise ValueError("Portable transfer directory must be private (0700)")
    directory = Path(tempfile.mkdtemp(prefix="deploy-", dir=transfers))
    bundle_path = directory / "session.json"
    arguments = ["--profile", browser_profile, "--expected-account-id", expected_account_id]
    if expected_username is not None:
        arguments += ["--expected-username", expected_username]
    remote_cli = '"$HOME/.local/bin/' + tool + '"'
    # Capability discovery emits help only, before any local browser opens.
    probe = run_on_server_raw(remote_cli + " auth session-import --help", timeout=30)
    if probe.returncode != 0 or not all(flag in probe.stdout for flag in ("--stdin", "--expected-account-id", "--profile")):
        directory.rmdir()
        raise ValueError("Remote owning CLI does not support portable session import")
    try:
        exported = subprocess.run([str(executable), "auth", "session-export", *arguments, "--output", str(bundle_path)],
                                  capture_output=True, text=True, timeout=180)
        if exported.returncode != 0 or not bundle_path.is_file() or bundle_path.is_symlink():
            raise ValueError("Owning service session export failed")
        metadata = bundle_path.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_size > PORTABLE_SESSION_MAX_BYTES:
            raise ValueError("Portable session export file is not private or exceeds size limit")
        payload = bundle_path.read_text(encoding="utf-8")
        bundle = read_session_bundle(payload)
        if bundle["tool"] != tool or bundle["profile"] != browser_profile or bundle["identity"]["account_id"] != expected_account_id or (
            expected_username is not None and bundle["identity"]["username"].casefold() != expected_username.casefold()
        ):
            raise ValueError("Portable session export identity mismatch")
        remote_command = remote_cli + " auth session-import --stdin " + shlex.join(arguments)
        imported = run_on_server_raw(remote_command, timeout=240, input_data=payload)
        if imported.returncode != 0:
            raise ValueError("Remote portable session import failed; private backup retained")
        result = json.loads(imported.stdout)
        if result.get("imported") is not True or result.get("verified") is not True or result.get("active") is not False or result.get("profile") != browser_profile or result.get("tool") != tool or result.get("identity", {}).get("account_id") != expected_account_id or (
            expected_username is not None and result.get("identity", {}).get("username", "").casefold() != expected_username.casefold()
        ):
            raise ValueError("Remote portable session identity was not verified")
        bundle_path.unlink()
        directory.rmdir()
        print_json({"tool": tool, "profile": browser_profile, "identity": result["identity"],
                    "imported": True, "verified": True, "active": False})
    except Exception:
        # Never disclose subprocess stderr, bundle contents, or parser errors.
        raise ValueError("Portable browser session deployment failed; private backup retained") from None


def _get_current_version() -> str:
    """Get the currently installed n8n version from the server binary."""
    return run_on_server(f"{N8N_BIN} --version").strip()


def _get_latest_version() -> str:
    """Get the latest n8n version available on npm."""
    output = run_on_server("npm view n8n version").strip()
    return output


@app.command("upgrade")
@command
def upgrade(
    version: str = typer.Argument(None, help="Target version (default: latest)"),
    skip_restart: bool = typer.Option(False, "--skip-restart", help="Skip n8n server restart"),
):
    """
    Upgrade n8n to the latest version (or a specific version).

    Installs the new version globally via npm, restarts the n8n
    LaunchDaemon, and verifies the server is healthy.

    Examples:
        n8n server upgrade
        n8n server upgrade 2.10.0
        n8n server upgrade --skip-restart
    """
    try:
        # Step 1: Get current version
        print_info("[1/4] Checking current version...")
        current = _get_current_version()
        print_info(f"Current version: {current}")

        # Step 2: Determine target version
        if version:
            target = version
        else:
            print_info("[2/4] Checking latest version...")
            target = _get_latest_version()

        if target == current:
            print_success(f"Already on version {current}")
            print_json({"current": current, "target": target, "upgraded": False})
            raise typer.Exit(0)

        print_info(f"Target version: {target}")

        # Step 3: Install
        print_info(f"[3/4] Installing n8n@{target}...")
        result = run_on_server_raw(
            f"sudo npm install -g --prefix {N8N_INSTALL_PREFIX} n8n@{target}",
            timeout=300,
        )
        if result.returncode != 0:
            print_error(f"npm install failed: {result.stderr.strip()}")
            raise typer.Exit(1)

        # Verify the binary was updated
        installed = _get_current_version()
        if installed != target:
            print_error(f"Version mismatch after install: expected {target}, got {installed}")
            raise typer.Exit(1)

        print_success(f"Installed n8n@{target}")

        # Step 4: Restart
        if not skip_restart:
            print_info("[4/4] Restarting n8n...")
            restart_n8n()
            print_success("n8n restarted and ready")
        else:
            print_info("[4/4] Skipping restart")

        print_json({"current": current, "target": target, "upgraded": True})

    except typer.Exit:
        raise
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except N8nApiError as e:
        print_error(f"n8n failed to start after upgrade: {e}")
        print_info("Check logs: n8n server logs app")
        raise typer.Exit(1)


@app.command("version")
@command
def server_version():
    """
    Show the n8n server version.

    Example:
        n8n server version
    """
    try:
        current = _get_current_version()
        print_json({"version": current})
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("restart")
@command
def restart():
    """
    Restart the n8n server.

    Example:
        n8n server restart
    """
    try:
        print_info("Restarting n8n...")
        restart_n8n()
        print_success("n8n restarted and ready")
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except N8nApiError as e:
        print_error(f"n8n failed to start: {e}")
        print_info("Check logs: n8n server logs app")
        raise typer.Exit(1)
