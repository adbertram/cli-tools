"""Nodes commands - manage n8n node packages (list, create, deploy, test, tools)."""
import enum
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from ..package_inventory import list_server_packages, node_belongs_to_package, package_map
from .test import test_node
from .convert import convert_cli_tool
from .deploy import deploy_node
from .remove import remove_node
from .install import install_node
from .tools import app as tools_app

app = typer.Typer(help="Manage n8n node packages", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "cli-tools": [
        "api_key"
    ],
    "create": [
        "api_key"
    ],
    "deploy": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "install": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "remove": [
        "api_key"
    ],
    "test": [
        "api_key"
    ]
}
app.command("test")(test_node)
app.command("create")(convert_cli_tool)
app.command("deploy")(deploy_node)
app.command("remove")(remove_node)
app.command("install")(install_node)
app.add_typer(tools_app, name="cli-tools", help="List and inspect available CLI tools for node conversion")


class NodeType(str, enum.Enum):
    default = "default"
    community = "community"
    custom = "custom"


def _package_for_node(node_name: str, packages_by_name: dict) -> Optional[dict]:
    for package_name, package in packages_by_name.items():
        if node_belongs_to_package(node_name, package_name):
            return package
    return None


@app.command("list")
def nodes_list(
    node_type: Optional[NodeType] = typer.Option(None, "--type", help="Node source: 'default', 'community' (third-party), or 'custom' (generated)"),
    include_tools: bool = typer.Option(False, "--include-tools", help="Include auto-generated AI tool variants"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List n8n node packages.

    Without --type, lists locally generated packages (from nodes create).
    With --type, queries the n8n server for installed nodes.

    Example:
        n8n nodes list                    # locally generated packages
        n8n nodes list --type default     # built-in nodes on server
        n8n nodes list --type community   # third-party community nodes on server
        n8n nodes list --type custom      # generated/custom packages on server
        n8n nodes list --type community --include-tools --table
    """
    try:
        if node_type is not None:
            # Query the n8n server
            from ..n8n_api import get_n8n_api_client
            api_client = get_n8n_api_client()
            if node_type == NodeType.default:
                data = api_client.list_nodes("default", include_tools=include_tools)
            else:
                packages = list_server_packages()
                packages_by_name = package_map(packages)
                data = api_client.list_nodes("community", include_tools=include_tools)
                for node in data:
                    package = _package_for_node(node["name"], packages_by_name)
                    node["packageName"] = package["packageName"] if package else node["name"].rsplit(".", 1)[0]
                    node["packageType"] = package["packageType"] if package else "community"

                if node_type == NodeType.community:
                    data = [node for node in data if node.get("packageType") == "community"]
                elif node_type == NodeType.custom:
                    data = [node for node in data if node.get("packageType") == "custom"]

            if filter:
                data = apply_filters(data, filter)

            data = apply_limit(data, limit)

            if properties:
                data = apply_properties_filter(data, properties)

            if table:
                if properties:
                    fields = [f.strip() for f in properties.split(",")]
                    print_table(data, fields, fields)
                else:
                    print_table(
                        data,
                        ["name", "displayName", "version", "packageName", "packageType"],
                        ["Node Type", "Display Name", "Version", "Package", "Package Type"],
                    )
            else:
                print_json(data)
        else:
            # List locally generated packages (original behavior)
            client = get_client()
            packages = client.list_generated()

            data = [p.model_dump() for p in packages]

            if filter:
                data = apply_filters(data, filter)

            data = apply_limit(data, limit)

            if properties:
                data = apply_properties_filter(data, properties)

            if table:
                if properties:
                    fields = [f.strip() for f in properties.split(",")]
                    print_table(data, fields, fields)
                else:
                    print_table(
                        data,
                        ["name", "cli_tool", "output_dir"],
                        ["Package", "CLI Tool", "Path"],
                    )
            else:
                print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def nodes_get(
    name: str = typer.Argument(..., help="Package name, CLI tool name, or built-in node name"),
    node_type: Optional[NodeType] = typer.Option(None, "--type", help="Node source: 'default' (built-in) or 'community'"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a node package or built-in node.

    Without --type, looks up locally generated packages.
    With --type, fetches the full node definition from the n8n server.

    Example:
        n8n nodes get brickowl
        n8n nodes get slack --type default
        n8n nodes get slack --type default --table
    """
    try:
        if node_type is not None:
            from ..n8n_api import get_n8n_api_client, parse_node_resources
            from cli_tools_shared.output import print_error
            api_client = get_n8n_api_client()
            node_def = api_client.get_node_definition(name)

            if not node_def:
                print_error(f"No node found matching '{name}'")
                raise typer.Exit(1)

            if table:
                # Build resource → operations summary
                res_map = parse_node_resources(node_def)
                res_summary = []
                for res, ops in res_map.items():
                    op_names = ", ".join(o["value"] for o in ops)
                    res_summary.append(f"{res}: {op_names}")

                creds = node_def.get("credentials", [])
                cred_names = ", ".join(c.get("name", "") for c in creds if isinstance(c, dict))

                rows = [
                    {"field": "name", "value": node_def.get("name", "")},
                    {"field": "displayName", "value": node_def.get("displayName", "")},
                    {"field": "description", "value": node_def.get("description", "")},
                    {"field": "version", "value": str(node_def.get("defaultVersion") or node_def.get("version", ""))},
                    {"field": "credentials", "value": cred_names},
                ]
                for line in res_summary:
                    rows.append({"field": "resource → operations", "value": line})

                print_table(rows, ["field", "value"], ["Field", "Value"])
            else:
                print_json(node_def)
        else:
            client = get_client()
            packages = client.list_generated()

            # Find matching package
            match = None
            for pkg in packages:
                if pkg.cli_tool == name or pkg.name == name:
                    match = pkg
                    break

            if not match:
                from cli_tools_shared.output import print_error
                print_error(f"No generated package found for '{name}'")
                raise typer.Exit(1)

            if table:
                data = match.model_dump()
                rows = [{"field": k, "value": str(v)} for k, v in data.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
            else:
                print_json(match)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
