"""Plugin commands for WordPress CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_filters, apply_limit
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info
from . import model_to_dict, extract_fields


app = typer.Typer(help="Manage WordPress plugins")

COMMAND_CREDENTIALS = {
    "list": ["username_password"],
    "get": ["username_password"],
    "activate": ["username_password"],
    "deactivate": ["username_password"],
    "delete": ["username_password"],
    "install": ["username_password"],
    "upgrade": ["username_password"],
}


UPDATE_FIELDS = {"update_status", "update_version", "latest_version", "latest_version_source"}


def get_client():
    from ..client import get_client as _get_client
    return _get_client()


def requires_update_status(properties: Optional[str]) -> bool:
    if not properties:
        return False
    fields = {field.strip() for field in properties.split(",")}
    return bool(fields & UPDATE_FIELDS)


@app.command("list")
def plugins_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of plugins to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., plugin:contains:acf, status:eq:active)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (active, inactive)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List installed WordPress plugins."""
    try:
        client = get_client()
        plugins = client.list_plugins(include_update_status=requires_update_status(properties))

        # Convert to dicts for filtering
        plugin_dicts = [model_to_dict(p) for p in plugins]

        # Filter by status if specified
        if status:
            plugin_dicts = [p for p in plugin_dicts if p.get("status") == status]
        if filter:
            plugin_dicts = apply_filters(plugin_dicts, filter)
        plugin_dicts = apply_limit(plugin_dicts, limit)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            plugin_dicts = extract_fields(plugin_dicts, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(plugin_dicts, fields, fields)
            else:
                print_table(
                    plugin_dicts,
                    ["plugin", "name", "version", "status", "auto_update"],
                    ["Plugin", "Name", "Version", "Status", "Auto Update"],
                )
        else:
            print_json(plugin_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def plugins_get(
    plugin: str = typer.Argument(..., help="Plugin identifier (e.g. mailchimp-for-wp/mailchimp-for-wp)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """Get details for a specific WordPress plugin."""
    try:
        client = get_client()
        result = client.get_plugin(plugin, include_update_status=requires_update_status(properties))

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            result = extract_fields([result], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([result], fields, fields)
            else:
                plugin_dict = model_to_dict(result)
                rows = [{"field": k, "value": str(v)} for k, v in plugin_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("activate")
def plugins_activate(
    plugin: str = typer.Argument(..., help="Plugin identifier (e.g. mailchimp-for-wp/mailchimp-for-wp)"),
):
    """Activate a WordPress plugin."""
    try:
        client = get_client()
        print_info(f"Activating plugin: {plugin}")
        result = client.update_plugin(plugin, {"status": "active"})
        print_success(f"Plugin {result.name} activated (v{result.version})")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("deactivate")
def plugins_deactivate(
    plugin: str = typer.Argument(..., help="Plugin identifier (e.g. mailchimp-for-wp/mailchimp-for-wp)"),
):
    """Deactivate a WordPress plugin."""
    try:
        client = get_client()
        print_info(f"Deactivating plugin: {plugin}")
        result = client.update_plugin(plugin, {"status": "inactive"})
        print_success(f"Plugin {result.name} deactivated")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def plugins_delete(
    plugin: str = typer.Argument(..., help="Plugin identifier (e.g. mailchimp-for-wp/mailchimp-for-wp)"),
):
    """Delete (uninstall) a WordPress plugin. Must be inactive first."""
    try:
        client = get_client()
        print_info(f"Deleting plugin: {plugin}")
        result = client.delete_plugin(plugin)
        print_success(f"Plugin {plugin} deleted")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("install")
def plugins_install(
    slug: str = typer.Argument(..., help="Plugin slug from wordpress.org (e.g. mailchimp-for-wp)"),
    activate: bool = typer.Option(False, "--activate", "-a", help="Activate after installation"),
):
    """Install a plugin from wordpress.org."""
    try:
        client = get_client()
        print_info(f"Installing plugin: {slug}")
        result = client.install_plugin(slug, activate=activate)
        status_msg = "and activated" if activate else "(inactive)"
        print_success(f"Plugin {result.name} v{result.version} installed {status_msg}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("upgrade")
def plugins_upgrade(
    plugin: str = typer.Argument(..., help="Plugin identifier (e.g. mailchimp-for-wp/mailchimp-for-wp)"),
):
    """Upgrade a plugin to the latest version through Jetpack's native updater."""
    try:
        client = get_client()
        current = client.get_plugin(plugin)
        print_info(f"Upgrading {current.name} from v{current.version}...")

        result = client.upgrade_plugin(plugin)
        print_success(f"Plugin {result.name} upgraded to v{result.version} (status: {result.status})")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
