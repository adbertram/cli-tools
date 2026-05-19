"""Deploy command - build, sync, install, and verify an n8n node on the server.

Installs to the community nodes directory (/var/root/.n8n/nodes/) via npm install.
n8n auto-discovers packages in this directory without any extra env vars.
"""
import subprocess
import time
from pathlib import Path
import typer

from ..config import get_config
from ..parser import parse_cli_tool, ParserError
from ..n8n_api import get_n8n_api_client, N8nApiError
from ..output import print_error, print_info, print_success, print_json


N8N_SERVER_HOST = "adam-server"
N8N_NODES_DIR = "/var/root/.n8n/nodes"
N8N_PLIST = "/Library/LaunchDaemons/com.n8n.server.plist"
N8N_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

RSYNC_EXCLUDES = [
    ".venv",
    "venv",
    "__pycache__",
    "*.egg-info",
    "node_modules",
    ".git",
]


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Read a .env file and return a dict of key-value pairs."""
    env_vars = {}
    if not env_path.exists():
        return env_vars
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key != "IS_DEFAULT_PROFILE":
            env_vars[key] = value
    return env_vars


def _find_default_env_file(tool_dir: Path) -> Path | None:
    """Find the default .env file for a CLI tool (IS_DEFAULT_PROFILE=1 or bare .env)."""
    # Check all .env files for IS_DEFAULT_PROFILE=1
    env_files = []
    bare = tool_dir / ".env"
    if bare.exists():
        env_files.append(bare)
    for f in sorted(tool_dir.glob(".env.*")):
        if f.name != ".env.example":
            env_files.append(f)

    for f in env_files:
        try:
            for line in f.read_text().splitlines():
                if line.strip().startswith("IS_DEFAULT_PROFILE=1"):
                    return f
        except OSError:
            continue

    # Fall back to bare .env
    if bare.exists():
        return bare

    # Fall back to first profile file
    return env_files[0] if env_files else None


def _run_local(cmd: list[str], cwd: str = None, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a local command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)


def _run_ssh(cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a command on the n8n server via SSH."""
    return subprocess.run(
        ["ssh", N8N_SERVER_HOST, cmd],
        capture_output=True, text=True, timeout=timeout,
    )


def deploy_node(
    node_name: str = typer.Argument(..., help="Node name to deploy (e.g., brickowl)"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip npm install and build"),
    skip_restart: bool = typer.Option(False, "--skip-restart", help="Skip n8n server restart"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip node verification"),
):
    """
    Deploy an n8n node package to the n8n server (adam-server).

    Performs the full pipeline: build TypeScript, rsync to server, npm install
    into community nodes dir (~/.n8n/nodes/), install bundled CLI venv, create
    n8n credentials from CLI .env, restart n8n, and verify the node loads.

    Example:
        n8n-node deploy brickowl
        n8n-node deploy brickowl --skip-build
    """
    # Strip n8n-nodes- prefix if user passed full package name
    if node_name.startswith("n8n-nodes-"):
        node_name = node_name[len("n8n-nodes-"):]

    config = get_config()
    package_dir = f"{config.output_dir}/n8n-nodes-{node_name}"
    package_name = f"n8n-nodes-{node_name}"

    # Verify package exists locally
    if not Path(package_dir).is_dir():
        print_error(f"Package not found: {package_dir}")
        print_info("Run 'n8n-node convert-cli-tool {node_name}' first.")
        raise typer.Exit(1)

    # Step 1: Build
    if not skip_build:
        print_info(f"[1/7] Building {package_name}...")

        result = _run_local(["npm", "install"], cwd=package_dir)
        if result.returncode != 0:
            print_error(f"npm install failed: {result.stderr or result.stdout}")
            raise typer.Exit(1)

        result = _run_local(["npm", "run", "build"], cwd=package_dir)
        if result.returncode != 0:
            print_error(f"npm run build failed: {result.stderr or result.stdout}")
            raise typer.Exit(1)

        print_success("Build complete")
    else:
        print_info("[1/7] Skipping build")

    # Step 2: Rsync to server temp dir
    print_info(f"[2/7] Syncing {package_name} to {N8N_SERVER_HOST}...")

    tmp_dir = f"/tmp/{package_name}"
    # Use sudo to remove temp dir — previous deploys may leave root-owned files (from CLI venv install)
    _run_ssh(f"sudo rm -rf {tmp_dir}")
    result = _run_ssh(f"mkdir -p {tmp_dir}")
    if result.returncode != 0:
        print_error(f"Failed to create temp dir: {result.stderr}")
        raise typer.Exit(1)

    rsync_cmd = ["rsync", "-az", "--delete"]
    for exclude in RSYNC_EXCLUDES:
        rsync_cmd.extend(["--exclude", exclude])
    rsync_cmd.extend([
        f"{package_dir}/",
        f"{N8N_SERVER_HOST}:{tmp_dir}/",
    ])

    result = _run_local(rsync_cmd)
    if result.returncode != 0:
        print_error(f"rsync failed: {result.stderr or result.stdout}")
        raise typer.Exit(1)

    print_success("Sync complete")

    # Step 3: Pack and install into community nodes dir
    # npm install <local-path> creates a symlink — use npm pack + install tarball to get a real copy
    print_info(f"[3/7] Installing {package_name} to community nodes...")

    pack_cmd = (
        f'sudo bash -c "cd {tmp_dir} && '
        f'PATH={N8N_PATH} /usr/local/bin/npm pack --pack-destination /tmp"'
    )
    result = _run_ssh(pack_cmd, timeout=60)
    if result.returncode != 0:
        print_error(f"npm pack failed: {result.stderr or result.stdout}")
        raise typer.Exit(1)

    # npm pack outputs the tarball filename on the last line
    tarball_name = result.stdout.strip().split('\n')[-1]
    tarball_path = f"/tmp/{tarball_name}"

    install_cmd = (
        f'sudo bash -c "cd {N8N_NODES_DIR} && '
        f'PATH={N8N_PATH} /usr/local/bin/npm install {tarball_path} --save"'
    )
    result = _run_ssh(install_cmd, timeout=180)
    if result.returncode != 0:
        print_error(f"npm install failed: {result.stderr or result.stdout}")
        raise typer.Exit(1)

    # Clean up tarball
    _run_ssh(f"sudo rm -f {tarball_path}")

    print_success("Installed to community nodes")

    # Step 4: Install bundled CLI venv
    installed_cli_dir = f"{N8N_NODES_DIR}/node_modules/{package_name}/cli"
    print_info("[4/7] Installing bundled CLI venv...")

    check_result = _run_ssh(f"sudo test -f {installed_cli_dir}/pyproject.toml && echo exists")
    if check_result.returncode == 0 and "exists" in check_result.stdout:
        # Create venv and install (editable so __file__ points to source dir for .env resolution).
        # cli-tools-shared is resolved via local file reference in pyproject.toml (patched during bundle step)
        venv_cmd = (
            f'sudo bash -c "cd {installed_cli_dir} && '
            f'python3 -m venv .venv && '
            f'.venv/bin/pip install --upgrade pip --quiet && '
            f'.venv/bin/pip install -e . --quiet"'
        )
        result = _run_ssh(venv_cmd, timeout=180)
        if result.returncode != 0:
            print_error(f"CLI venv install failed: {result.stderr or result.stdout}")
            raise typer.Exit(1)

        # Copy CLI .env to server so the CLI can authenticate via its profile system
        tool_dir = Path(config.cli_tools_dir) / node_name
        env_file = _find_default_env_file(tool_dir)
        if env_file:
            scp_result = _run_local(
                ["scp", str(env_file), f"{N8N_SERVER_HOST}:/tmp/{package_name}.env"]
            )
            if scp_result.returncode == 0:
                cp_result = _run_ssh(
                    f'sudo cp /tmp/{package_name}.env {installed_cli_dir}/.env && '
                    f'sudo chmod 600 {installed_cli_dir}/.env && '
                    f'sudo rm -f /tmp/{package_name}.env'
                )
                if cp_result.returncode == 0:
                    print_success("CLI .env copied to server")
                else:
                    print_error(f"Failed to copy .env to CLI dir: {cp_result.stderr}")
            else:
                print_error(f"Failed to SCP .env: {scp_result.stderr}")
        else:
            print_info("No CLI .env file found locally, skipping")

        print_success("CLI venv installed")
    else:
        print_info("No bundled CLI found, skipping venv install")

    # Step 5: Restart n8n (must happen before credential creation so n8n knows the new credential type)
    if not skip_restart:
        print_info("[5/7] Restarting n8n...")

        result = _run_ssh(f"sudo launchctl unload {N8N_PLIST}")
        if result.returncode != 0:
            print_error(f"Failed to stop n8n: {result.stderr}")
            raise typer.Exit(1)

        time.sleep(2)

        result = _run_ssh(f"sudo launchctl load {N8N_PLIST}")
        if result.returncode != 0:
            print_error(f"Failed to start n8n: {result.stderr}")
            raise typer.Exit(1)

        print_info("Waiting for n8n to start...")
        time.sleep(5)

        print_success("n8n restarted")
    else:
        print_info("[5/7] Skipping restart")

    # Step 6: Create n8n credential from CLI tool's .env
    # Runs after restart so n8n has loaded the new credential type schema
    print_info(f"[6/7] Creating credential for {node_name}...")

    try:
        metadata = parse_cli_tool(node_name, config.cli_tools_dir)
    except ParserError as e:
        print_error(f"Failed to parse CLI tool metadata: {e}")
        raise typer.Exit(1)

    if metadata.credentials:
        # Find the CLI tool's .env file with actual values
        tool_dir = Path(config.cli_tools_dir) / node_name
        env_file = _find_default_env_file(tool_dir)
        if not env_file:
            print_error(f"No .env file found in {tool_dir}")
            raise typer.Exit(1)

        env_values = _read_env_file(env_file)

        # Build credential data: map n8n field names to env var values
        cred_data = {}
        for cred_field in metadata.credentials:
            value = env_values.get(cred_field.env_var, "")
            if value:
                cred_data[cred_field.field_name] = value

        if cred_data:
            # camelCase credential type name: airtable -> airtableApi
            camel_name = node_name.split("-")
            camel_name = camel_name[0] + "".join(w.title() for w in camel_name[1:])
            cred_type = f"{camel_name}Api"
            cred_display_name = f"{metadata.display_name} API"

            try:
                api = get_n8n_api_client()

                # Check if credential of this type already exists
                existing = api.list_credentials()
                existing_cred = next(
                    (c for c in existing if c["type"] == cred_type), None
                )

                if existing_cred:
                    # Update existing credential
                    api._request(
                        "PATCH",
                        f"/credentials/{existing_cred['id']}",
                        json={"name": cred_display_name, "type": cred_type, "data": cred_data},
                    )
                    print_success(f"Updated credential: {cred_display_name} (id: {existing_cred['id']})")
                else:
                    # Create new credential
                    result = api.create_credential(cred_display_name, cred_type, cred_data)
                    print_success(f"Created credential: {cred_display_name} (id: {result['id']})")
            except N8nApiError as e:
                print_error(f"Credential creation failed: {e}")
                print_info("You may need to create credentials manually in the n8n UI.")
        else:
            print_info("No credential values found in .env, skipping")
    else:
        print_info("No credentials defined, skipping")

    # Step 7: Verify node loaded as community node
    if not skip_verify:
        print_info(f"[7/7] Verifying {package_name}...")

        try:
            api = get_n8n_api_client()
            nodes = api.list_nodes(node_type="community")
            found = [n for n in nodes if n["name"].startswith(f"{package_name}.")]

            if not found:
                # Fall back to checking all nodes in case community detection fails
                nodes = api.list_nodes(node_type="all")
                found = [n for n in nodes if n["name"].startswith(f"{package_name}.")]

            if found:
                print_success(f"Verified: {len(found)} node(s) registered")
                print_json({"deployed": package_name, "nodes": found})
            else:
                print_error(f"Node {package_name} not found after deploy")
                print_info("Check n8n logs: ssh adam-server 'sudo tail -50 /var/log/n8n.log'")
                raise typer.Exit(1)
        except N8nApiError as e:
            print_error(f"Verification failed: {e}")
            print_info("n8n may still be starting. Try: n8n-node nodes list")
            raise typer.Exit(1)
    else:
        print_info("[7/7] Skipping verification")
        print_success(f"Deploy complete: {package_name}")

    # Cleanup temp dir (sudo needed — CLI venv install creates root-owned files)
    _run_ssh(f"sudo rm -rf {tmp_dir}")
