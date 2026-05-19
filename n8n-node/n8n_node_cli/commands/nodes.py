"""Nodes commands - list and inspect generated n8n node packages."""
import enum
import typer
from typing import Optional, List

from ..client import get_client
from ..output import print_json, print_table, handle_error
from ..filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="List and inspect generated n8n node packages", no_args_is_help=True)


class NodeType(str, enum.Enum):
    default = "default"
    community = "community"


@app.command("list")
def nodes_list(
    node_type: Optional[NodeType] = typer.Option(None, "--type", help="Node source: 'default' (built-in) or 'community' (installed packages)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List n8n node packages.

    Without --type, lists locally generated packages (from convert-cli-tool).
    With --type, queries the n8n server for installed nodes.

    Example:
        n8n-node nodes list                    # locally generated packages
        n8n-node nodes list --type default     # built-in nodes on server
        n8n-node nodes list --type community   # community nodes on server
        n8n-node nodes list --type community --table
    """
    try:
        if node_type is not None:
            # Query the n8n server
            from ..n8n_api import get_n8n_api_client
            api_client = get_n8n_api_client()
            data = api_client.list_nodes(node_type.value)

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
                        ["name", "displayName", "version"],
                        ["Node Type", "Display Name", "Version"],
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
    name: str = typer.Argument(..., help="Package name or CLI tool name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific generated n8n node package.

    Example:
        n8n-node nodes get brickowl
        n8n-node nodes get brickowl --table
    """
    try:
        client = get_client()
        packages = client.list_generated()

        # Find matching package
        match = None
        for pkg in packages:
            if pkg.cli_tool == name or pkg.name == name or pkg.name == f"n8n-nodes-{name}":
                match = pkg
                break

        if not match:
            from ..output import print_error
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
