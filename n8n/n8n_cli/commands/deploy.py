"""Deploy command - build, sync, install, and verify an n8n node on the server.

Installs to the community nodes directory (/var/root/.n8n/nodes/) via npm install.
n8n auto-discovers packages in this directory without any extra env vars.
"""
import json
import subprocess
import time
from pathlib import Path
import typer

from cli_tools_shared.config import get_profiles_base_dir

from ..config import get_config
from ..parser import parse_cli_tool, ParserError
from ..n8n_api import get_n8n_api_client, N8nApiError
from cli_tools_shared.output import print_error, print_info, print_success, print_json
from ..server import run_on_server_raw, sync_to_server, copy_file_to_server, get_server_host


N8N_NODES_DIR = "/Users/adam/.n8n/nodes"
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



def _check_browser_session(node_name: str, config) -> bool:
    """Check if the CLI tool's browser session is authenticated.

    Runs `{cli_command} auth status` via the tool's local venv and checks
    the `browser_session` field in the JSON output.

    Returns True if authenticated, False otherwise.
    """
    tool_dir = Path(config.cli_tools_dir) / node_name

    try:
        metadata = parse_cli_tool(node_name, config.cli_tools_dir)
    except ParserError:
        return True  # Can't parse metadata, skip check

    if "browser_session" not in (metadata.credential_types or []):
        print_info("No browser session required, skipping")
        return True

    cli_command = metadata.cli_command or node_name
    venv_bin = tool_dir / ".venv" / "bin" / cli_command

    if not venv_bin.exists():
        print_error(f"CLI venv not found: {venv_bin}")
        print_info(f"Run: cd {tool_dir} && python3 -m venv .venv && .venv/bin/pip install -e .")
        return False

    try:
        result = _run_local([str(venv_bin), "auth", "status"], cwd=str(tool_dir), timeout=30)
    except subprocess.TimeoutExpired:
        print_error("Timed out checking browser session status")
        return False

    if result.returncode != 0:
        print_error(f"Browser session check failed: {result.stderr or result.stdout}")
        print_info(f"Run: {cli_command} auth login")
        return False

    try:
        status = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        print_error(f"Could not parse auth status output: {result.stdout}")
        print_info(f"Run: {cli_command} auth login")
        return False

    if not status.get("browser_session"):
        print_error("Browser session is not authenticated")
        print_info(f"Run: {cli_command} auth login")
        return False

    return True


def deploy_node(
    package_path: str = typer.Argument(..., help="Path to the n8n node package directory"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip npm install and build"),
    skip_restart: bool = typer.Option(False, "--skip-restart", help="Skip n8n server restart"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip node verification"),
    skip_auth_check: bool = typer.Option(False, "--skip-auth-check", help="Skip browser session auth check"),
):
    """
    Deploy an n8n node package to the n8n server (adam-server).

    Performs the full pipeline: build TypeScript, rsync to server, npm install
    into community nodes dir (~/.n8n/nodes/), install bundled CLI venv, create
    n8n credentials from CLI .env, restart n8n, and verify the node loads.

    Example:
        n8n nodes deploy shippo
        n8n nodes deploy ~/Dropbox/GitRepos/n8n-nodes/brickowl
        n8n nodes deploy ~/Dropbox/GitRepos/n8n-nodes-claudecode
        n8n nodes deploy ~/Dropbox/GitRepos/n8n-nodes/brickowl --skip-build
    """
    config = get_config()
    package_dir = str(Path(package_path).expanduser().resolve())

    # If path doesn't exist, try resolving as a package name in the output directory
    if not Path(package_dir).is_dir():
        candidate = Path(config.output_dir) / Path(package_path).name
        if candidate.is_dir():
            package_dir = str(candidate)
        else:
            print_error(f"Package not found: {package_dir}")
            print_error(f"Also checked: {candidate}")
            raise typer.Exit(1)

    # Read package name from package.json
    pkg_json_path = Path(package_dir) / "package.json"
    if not pkg_json_path.exists():
        print_error(f"No package.json found in {package_dir}")
        raise typer.Exit(1)

    pkg_json = json.loads(pkg_json_path.read_text())
    package_name = pkg_json["name"]

    # Auto-increment patch version
    old_version = pkg_json.get("version", "0.0.0")
    parts = old_version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    new_version = ".".join(parts)
    pkg_json["version"] = new_version
    pkg_json_path.write_text(json.dumps(pkg_json, indent=2) + "\n")
    print_info(f"Version: {old_version} → {new_version}")

    # Detect bundled CLI
    has_bundled_cli = (Path(package_dir) / "cli" / "pyproject.toml").exists()

    # Derive node_name from package directory name for CLI tool lookups.
    # If a bundled CLI exists, detect the original tool name from the CLI's
    # pyproject.toml entry point (handles name overrides during create).
    node_name = Path(package_dir).name
    if has_bundled_cli:
        cli_pyproject = Path(package_dir) / "cli" / "pyproject.toml"
        try:
            import re as _re
            _pp_content = cli_pyproject.read_text()
            # Extract the CLI command name from [project.scripts] section
            _script_match = _re.search(r'^\[project\.scripts\]\s*\n(\w[\w-]*)\s*=', _pp_content, _re.MULTILINE)
            if _script_match:
                cli_tool_name = _script_match.group(1)
            else:
                cli_tool_name = node_name
        except OSError:
            cli_tool_name = node_name
    else:
        cli_tool_name = node_name

    # Step 1: Pre-flight browser session check
    if not skip_auth_check:
        print_info("[1/8] Checking browser session auth...")
        if not _check_browser_session(cli_tool_name, config):
            raise typer.Exit(1)
        print_success("Browser session authenticated")
    else:
        print_info("[1/8] Skipping auth check")

    # Step 2: Build
    if not skip_build:
        print_info(f"[2/8] Building {package_name}...")

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
        print_info("[2/8] Skipping build")

    # Step 2: Rsync to server temp dir
    print_info(f"[3/8] Syncing {package_name} to server...")

    tmp_dir = f"/tmp/{package_name}"
    run_on_server_raw(f"rm -rf {tmp_dir}")
    result = run_on_server_raw(f"mkdir -p {tmp_dir}")
    if result.returncode != 0:
        print_error(f"Failed to create temp dir: {result.stderr}")
        raise typer.Exit(1)

    result = sync_to_server(package_dir, tmp_dir, excludes=RSYNC_EXCLUDES)
    if result.returncode != 0:
        print_error(f"rsync failed: {result.stderr or result.stdout}")
        raise typer.Exit(1)

    print_success("Sync complete")

    # Step 3: Pack and install into community nodes dir
    # npm install <local-path> creates a symlink — use npm pack + install tarball to get a real copy
    print_info(f"[4/8] Installing {package_name} to community nodes...")

    pack_cmd = (
        f'cd {tmp_dir} && '
        f'PATH={N8N_PATH} npm pack --pack-destination /tmp'
    )
    result = run_on_server_raw(pack_cmd, timeout=60)
    if result.returncode != 0:
        print_error(f"npm pack failed: {result.stderr or result.stdout}")
        raise typer.Exit(1)

    # npm pack outputs the tarball filename on the last line
    tarball_name = result.stdout.strip().split('\n')[-1]
    tarball_path = f"/tmp/{tarball_name}"

    install_cmd = (
        f'cd {N8N_NODES_DIR} && '
        f'PATH={N8N_PATH} npm install {tarball_path} --save --legacy-peer-deps'
    )
    result = run_on_server_raw(install_cmd, timeout=180)
    if result.returncode != 0:
        print_error(f"npm install failed: {result.stderr or result.stdout}")
        raise typer.Exit(1)

    # Clean up tarball
    run_on_server_raw(f"rm -f {tarball_path}")

    print_success("Installed to community nodes")

    # Step 4: Install bundled CLI venv (only for packages with a bundled CLI)
    installed_cli_dir = f"{N8N_NODES_DIR}/node_modules/{package_name}/cli"
    if has_bundled_cli:
        print_info("[5/8] Installing bundled CLI venv...")
        # Use the bundled install.sh which handles Python version selection
        # (e.g. preferring python3.13 over 3.14+ for pydantic-core/PyO3 compatibility)
        venv_cmd = f'bash {installed_cli_dir}/install.sh'
        result = run_on_server_raw(venv_cmd, timeout=180)
        if result.returncode != 0:
            print_error(f"CLI venv install failed: {result.stderr or result.stdout}")
            raise typer.Exit(1)

        # Copy CLI .env to server so the CLI can authenticate via its profile system
        tool_dir = Path(config.cli_tools_dir) / cli_tool_name
        env_file = _find_default_env_file(tool_dir)
        if env_file:
            scp_result = copy_file_to_server(str(env_file), f"/tmp/{package_name}.env")
            if scp_result.returncode == 0:
                cp_result = run_on_server_raw(
                    f'cp /tmp/{package_name}.env {installed_cli_dir}/.env && '
                    f'chmod 600 {installed_cli_dir}/.env && '
                    f'rm -f /tmp/{package_name}.env'
                )
                if cp_result.returncode == 0:
                    print_success("CLI .env copied to server")
                else:
                    print_error(f"Failed to copy .env to CLI dir: {cp_result.stderr}")
            else:
                print_error(f"Failed to copy .env: {scp_result.stderr}")
        else:
            print_info("No CLI .env file found locally, skipping")

        # Copy browser session data if this CLI uses browser_session credential type
        try:
            metadata_check = parse_cli_tool(cli_tool_name, config.cli_tools_dir)
            if "browser_session" in (metadata_check.credential_types or []):
                browser_data_dir = get_profiles_base_dir(cli_tool_name) / "default" / "browser-data"
                if browser_data_dir.is_dir():
                    # Ensure profiles directory exists on server
                    profiles_dir = f"{installed_cli_dir}/.profiles/default/browser-data"
                    run_on_server_raw(f"mkdir -p {profiles_dir}")

                    # Sync browser data to a temp location, then copy
                    tmp_browser = f"/tmp/{package_name}-browser-data"
                    br_result = sync_to_server(str(browser_data_dir), tmp_browser)
                    if br_result.returncode == 0:
                        cp_result = run_on_server_raw(
                            f'cp -R {tmp_browser}/* {profiles_dir}/ && '
                            f'rm -rf {tmp_browser}'
                        )
                        if cp_result.returncode == 0:
                            print_success("Browser session data copied to server")
                        else:
                            print_error(f"Failed to copy browser data: {cp_result.stderr}")
                    else:
                        print_error(f"Failed to rsync browser data: {br_result.stderr}")
                else:
                    print_info("No browser session data found locally (run 'auth login' first)")
        except ParserError:
            pass  # Non-fatal — metadata parsing may fail for some tools

        print_success("CLI venv installed")
    else:
        print_info("No bundled CLI found, skipping venv install")

    # Step 5: Restart n8n (must happen before credential creation so n8n knows the new credential type)
    if not skip_restart:
        print_info("[6/8] Restarting n8n...")

        result = run_on_server_raw(f"sudo launchctl unload {N8N_PLIST}")
        if result.returncode != 0:
            print_error(f"Failed to stop n8n: {result.stderr}")
            raise typer.Exit(1)

        time.sleep(2)

        result = run_on_server_raw(f"sudo launchctl load {N8N_PLIST}")
        if result.returncode != 0:
            print_error(f"Failed to start n8n: {result.stderr}")
            raise typer.Exit(1)

        print_info("Waiting for n8n to be ready...")
        try:
            api = get_n8n_api_client()
            api.wait_for_ready(timeout=60)
        except N8nApiError as e:
            print_error(f"n8n failed to start: {e}")
            print_info("Check logs: ssh adam-server 'sudo tail -50 /var/log/n8n.log'")
            raise typer.Exit(1)

        print_success("n8n restarted and ready")
    else:
        print_info("[6/8] Skipping restart")

    # Step 6: Create n8n credentials from CLI tool's .env (one per credential type)
    # Runs after restart so n8n has loaded the new credential type schemas
    if has_bundled_cli:
        print_info(f"[7/8] Creating credentials for {node_name}...")

        try:
            metadata = parse_cli_tool(cli_tool_name, config.cli_tools_dir)
        except ParserError as e:
            print_error(f"Failed to parse CLI tool metadata: {e}")
            raise typer.Exit(1)

        if metadata.credentials and metadata.credential_types:
            # Find the CLI tool's .env file with actual values
            tool_dir = Path(config.cli_tools_dir) / cli_tool_name
            env_file = _find_default_env_file(tool_dir)
            if not env_file:
                print_error(f"No .env file found in {tool_dir}")
                raise typer.Exit(1)

            env_values = _read_env_file(env_file)

            try:
                api = get_n8n_api_client()
                existing = api.list_credentials()

                pascal_name = "".join(w.title() for w in node_name.split("-"))

                # Maps for credential type naming (same as generator.py)
                cred_type_suffix = {
                    "api_key": "ApiKey", "oauth": "Oauth",
                    "oauth_authorization_code": "OauthCode",
                    "personal_access_token": "Pat",
                    "username_password": "UserPass",
                    "browser_session": "BrowserSession",
                }
                cred_type_display = {
                    "api_key": "API Key", "oauth": "OAuth",
                    "oauth_authorization_code": "OAuth Code",
                    "personal_access_token": "PAT",
                    "username_password": "User/Pass",
                    "browser_session": "Browser Session",
                }

                for ct in metadata.credential_types:
                    type_creds = [c for c in metadata.credentials if c.credential_type == ct]
                    if not type_creds:
                        continue

                    # Build credential type name (matches generator naming)
                    suffix = cred_type_suffix.get(ct, "".join(w.title() for w in ct.split("_")))
                    cred_class = f"{pascal_name}{suffix}"
                    cred_type = cred_class[0].lower() + cred_class[1:]
                    cred_display_name = f"{metadata.display_name} {cred_type_display.get(ct, ct.replace('_', ' ').title())}"

                    # Map n8n field names to env var values
                    # Include ALL fields (even empty) — n8n API requires all
                    # schema-defined properties to be present in the data object
                    cred_data = {}
                    has_values = False
                    for cred_field in type_creds:
                        value = env_values.get(cred_field.env_var, "")
                        cred_data[cred_field.field_name] = value
                        if value:
                            has_values = True

                    if not has_values:
                        print_info(f"No values found for {cred_display_name}, skipping")
                        continue

                    existing_cred = next(
                        (c for c in existing if c["type"] == cred_type), None
                    )

                    if existing_cred:
                        api._request(
                            "PATCH",
                            f"/credentials/{existing_cred['id']}",
                            json={"name": cred_display_name, "type": cred_type, "data": cred_data},
                        )
                        print_success(f"Updated credential: {cred_display_name} (id: {existing_cred['id']})")
                    else:
                        result = api.create_credential(cred_display_name, cred_type, cred_data)
                        print_success(f"Created credential: {cred_display_name} (id: {result['id']})")

            except N8nApiError as e:
                print_error(f"Credential creation failed: {e}")
                print_info("You may need to create credentials manually in the n8n UI.")
        else:
            print_info("No credentials defined, skipping")
    else:
        print_info("[7/8] No bundled CLI, skipping credential creation")

    # Step 7: Verify node loaded as community node
    if not skip_verify:
        print_info(f"[8/8] Verifying {package_name}...")

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
            print_info("n8n may still be starting. Try: n8n nodes list")
            raise typer.Exit(1)
    else:
        print_info("[8/8] Skipping verification")
        print_success(f"Deploy complete: {package_name}")

    # Cleanup temp dir
    run_on_server_raw(f"rm -rf {tmp_dir}")
