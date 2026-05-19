import typer

from ..n8n_api import get_n8n_api_client, N8nApiError
from cli_tools_shared.output import print_error, print_info, print_success, print_json, print_warning
from ..package_inventory import (
    follows_n8n_package_convention,
    list_server_packages,
    node_belongs_to_package,
)


def install_node(
    package_name: str = typer.Argument(..., help="npm package name (e.g., n8n-nodes-duckduckgo-search)"),
    version: str = typer.Option(None, "--version", help="Install a specific npm package version"),
    verify_vetted: bool = typer.Option(False, "--verify-vetted", help="Require n8n vetted-package verification"),
    skip_restart: bool = typer.Option(False, "--skip-restart", help="Deprecated; n8n REST installs load packages without restart"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip node verification after install"),
):
    """
    Install a third-party community node package from npm.

    Installs the package through the running n8n instance so npm runs in the
    same server/runtime environment that loads community packages.

    Example:
        n8n nodes install n8n-nodes-duckduckgo-search
        n8n nodes install @scope/n8n-nodes-example
        n8n nodes install n8n-nodes-example --version 1.2.3
        n8n nodes install n8n-nodes-mcp --skip-verify
    """
    if not follows_n8n_package_convention(package_name):
        print_warning(f"Package '{package_name}' does not follow the n8n-nodes-* naming convention")

    if skip_restart:
        print_info("--skip-restart accepted for compatibility; n8n REST installs do not restart")

    print_info(f"[1/2] Installing {package_name} through n8n...")
    try:
        api = get_n8n_api_client()
        installed_package = api.install_community_package(
            package_name,
            version=version,
            verify=verify_vetted,
        )
    except N8nApiError as e:
        print_error(f"Community package install failed: {e}")
        raise typer.Exit(1)
    if not isinstance(installed_package, dict) or not installed_package.get("packageName"):
        print_error(f"Unexpected install response from n8n: {installed_package}")
        raise typer.Exit(1)

    print_success(f"Installed {package_name}")

    if not skip_verify:
        print_info(f"[2/2] Verifying {package_name}...")

        try:
            packages = list_server_packages()
            installed = [p for p in packages if p["packageName"] == installed_package["packageName"]]
            nodes = api.list_nodes(node_type="all", include_tools=True)
            found = [
                node for node in nodes
                if node_belongs_to_package(node["name"], installed_package["packageName"])
            ]

            if not installed:
                print_error(f"Package {installed_package['packageName']} not found in server package inventory after install")
                raise typer.Exit(1)
            if not found:
                print_error(f"No loaded n8n nodes found for {installed_package['packageName']} after install")
                raise typer.Exit(1)

            print_success(f"Verified: {len(found)} node(s) registered")
            print_json({"installed": installed_package["packageName"], "packageType": "community", "nodes": found})
        except N8nApiError as e:
            print_error(f"Verification failed: {e}")
            print_info("n8n may still be starting. Try: n8n nodes list --type community")
            raise typer.Exit(1)
        except RuntimeError as e:
            print_error(f"Server package inventory failed: {e}")
            raise typer.Exit(1)
    else:
        print_info("[2/2] Skipping verification")
        print_json({"installed": installed_package["packageName"], "packageType": "community"})
