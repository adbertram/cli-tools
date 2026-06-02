"""Remove command - uninstall a community node from the n8n server."""
import time
import typer

from ..n8n_api import get_n8n_api_client, N8nApiError
from cli_tools_shared.output import print_error, print_info, print_success, print_json
from ..server import run_on_server_raw
from ..package_inventory import (
    list_server_packages,
    node_belongs_to_package,
    resolve_installed_package_name,
)
from .deploy import N8N_NODES_DIR, N8N_PLIST, N8N_PATH


def remove_node(
    node_name: str = typer.Argument(..., help="Node name to remove (e.g., brickowl)"),
    skip_restart: bool = typer.Option(False, "--skip-restart", help="Skip n8n server restart"),
    keep_credentials: bool = typer.Option(False, "--keep-credentials", help="Keep associated credentials"),
):
    """
    Remove a community node from the n8n server.

    Uninstalls the npm package from the community nodes directory,
    deletes associated credentials, and restarts n8n.

    Example:
        n8n nodes remove brickowl
        n8n nodes remove @scope/n8n-nodes-example
        n8n nodes remove airtable --keep-credentials
        n8n nodes remove ebay --skip-restart
    """
    try:
        packages = list_server_packages()
        package_name = resolve_installed_package_name(node_name, packages)
    except (RuntimeError, ValueError) as e:
        print_error(f"Server package inventory failed: {e}")
        raise typer.Exit(1)

    package = next((p for p in packages if p["packageName"] == package_name), None)
    if not package:
        print_error(f"{package_name} is not installed in {N8N_NODES_DIR}")
        raise typer.Exit(1)

    if package.get("packageType") == "community":
        print_info(f"[1/2] Uninstalling third-party package {package_name} through n8n...")
        try:
            api = get_n8n_api_client()
            api.uninstall_community_package(package_name)
        except N8nApiError as e:
            print_error(f"Community package uninstall failed: {e}")
            raise typer.Exit(1)

        print_info(f"[2/2] Verifying {package_name} removal...")
        nodes = api.list_nodes(node_type="all", include_tools=True)
        remaining = [n for n in nodes if node_belongs_to_package(n["name"], package_name)]
        if remaining:
            print_error(f"{package_name} still appears in loaded n8n nodes after removal")
            raise typer.Exit(1)
        print_success(f"Verified: {package_name} removed")
        print_json({"removed": package_name, "packageType": "community"})
        return

    short_name = package_name.replace("n8n-nodes-", "")

    # Step 1: Verify the package is installed
    print_info(f"[1/4] Checking if {package_name} is installed...")

    check_cmd = f'cd {N8N_NODES_DIR} && PATH={N8N_PATH} npm ls {package_name} --json 2>/dev/null'
    result = run_on_server_raw(check_cmd, timeout=30)

    if result.returncode != 0 or package_name not in result.stdout:
        print_error(f"{package_name} is not installed in {N8N_NODES_DIR}")
        raise typer.Exit(1)

    print_success(f"Found {package_name}")

    # Step 2: Delete credentials
    if not keep_credentials:
        print_info(f"[2/4] Removing credentials for {short_name}...")

        # Build expected credential type name (same logic as deploy.py)
        camel_parts = short_name.split("-")
        camel_name = camel_parts[0] + "".join(w.title() for w in camel_parts[1:])
        cred_type = f"{camel_name}Api"

        try:
            api = get_n8n_api_client()
            existing = api.list_credentials()
            matching = [c for c in existing if c["type"] == cred_type]

            if matching:
                for cred in matching:
                    api.delete_credential(cred["id"])
                    print_success(f"Deleted credential: {cred['name']} (id: {cred['id']})")
            else:
                print_info(f"No credentials found for type '{cred_type}'")
        except N8nApiError as e:
            print_error(f"Failed to remove credentials: {e}")
            print_info("You may need to remove credentials manually in the n8n UI.")
    else:
        print_info("[2/4] Keeping credentials (--keep-credentials)")

    # Step 3: Uninstall npm package
    print_info(f"[3/4] Uninstalling {package_name}...")

    uninstall_cmd = (
        f'cd {N8N_NODES_DIR} && '
        f'PATH={N8N_PATH} npm uninstall {package_name} --save'
    )
    result = run_on_server_raw(uninstall_cmd, timeout=120)
    if result.returncode != 0:
        print_error(f"npm uninstall failed: {result.stderr or result.stdout}")
        raise typer.Exit(1)

    print_success(f"Uninstalled {package_name}")

    # Step 4: Restart n8n
    if not skip_restart:
        print_info("[4/4] Restarting n8n...")

        result = run_on_server_raw(f"sudo launchctl unload {N8N_PLIST}")
        if result.returncode != 0:
            print_error(f"Failed to stop n8n: {result.stderr}")
            raise typer.Exit(1)

        time.sleep(2)

        result = run_on_server_raw(f"sudo launchctl load {N8N_PLIST}")
        if result.returncode != 0:
            print_error(f"Failed to start n8n: {result.stderr}")
            raise typer.Exit(1)

        print_info("Waiting for n8n to start...")
        time.sleep(5)

        # Verify node is gone
        try:
            api = get_n8n_api_client()
            nodes = api.list_nodes(node_type="community")
            remaining = [n for n in nodes if n["name"].startswith(f"{package_name}.")]

            if remaining:
                print_error(f"{package_name} still appears in community nodes after removal")
                raise typer.Exit(1)

            print_success(f"Verified: {package_name} removed")
        except N8nApiError as e:
            print_error(f"Verification failed: {e}")
            print_info("n8n may still be starting. Try: n8n nodes list --type community")
    else:
        print_info("[4/4] Skipping restart")

    print_json({"removed": package_name})
