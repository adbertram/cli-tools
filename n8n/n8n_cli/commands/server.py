"""Server commands - manage the n8n server instance."""
import json
import time
import typer

from ..n8n_api import get_n8n_api_client, N8nApiError
from cli_tools_shared.output import print_json, print_error, print_info, print_success
from ..server import run_on_server, run_on_server_raw
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
    ]
}

# Register logs as a sub-group: n8n server logs ...
app.add_typer(logs.app, name="logs", help="Query n8n server logs and configuration")
app.add_typer(server_config.app, name="config", help="Manage n8n server configuration")

N8N_BIN = "/usr/local/lib/node_modules/n8n/bin/n8n"
N8N_PLIST = "/Library/LaunchDaemons/com.n8n.server.plist"
N8N_INSTALL_PREFIX = "/usr/local"


def _get_current_version() -> str:
    """Get the currently installed n8n version from the server binary."""
    return run_on_server(f"{N8N_BIN} --version").strip()


def _get_latest_version() -> str:
    """Get the latest n8n version available on npm."""
    output = run_on_server("npm view n8n version").strip()
    return output


def _restart_n8n():
    """Stop and start the n8n LaunchDaemon, then wait for ready."""
    result = run_on_server_raw(f"sudo launchctl unload {N8N_PLIST}")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to stop n8n: {result.stderr.strip()}")

    time.sleep(2)

    result = run_on_server_raw(f"sudo launchctl load {N8N_PLIST}")
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start n8n: {result.stderr.strip()}")

    api = get_n8n_api_client()
    api.wait_for_ready(timeout=60)


@app.command("upgrade")
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
            _restart_n8n()
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
def restart():
    """
    Restart the n8n server.

    Example:
        n8n server restart
    """
    try:
        print_info("Restarting n8n...")
        _restart_n8n()
        print_success("n8n restarted and ready")
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except N8nApiError as e:
        print_error(f"n8n failed to start: {e}")
        print_info("Check logs: n8n server logs app")
        raise typer.Exit(1)
