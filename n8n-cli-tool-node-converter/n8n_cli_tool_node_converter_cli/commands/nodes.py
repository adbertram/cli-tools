"""Nodes commands - generate and manage n8n node packages."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from cli_tools_shared.output import handle_error, print_json, print_success, print_table

app = typer.Typer(help="Generate and manage n8n node packages", no_args_is_help=True)


@app.command("generate")
def nodes_generate(
    cli_name: str = typer.Argument(..., help="CLI tool name to convert"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Override output directory"),
    force: bool = typer.Option(False, "--force", "-F", help="Overwrite existing package"),
):
    """
    Generate an n8n node package from a CLI tool.

    Example:
        n8n-cli-tool-node-converter nodes generate brickowl
        n8n-cli-tool-node-converter nodes generate shippo --output-dir ./output
        n8n-cli-tool-node-converter nodes generate brickowl --force
    """
    try:
        client = get_client()
        pkg_path = client.generate(cli_name, output_dir=output_dir, force=force)
        print_success(f"Generated n8n node package at: {pkg_path}")

        # Show summary
        metadata = client.get_tool(cli_name)
        total_ops = sum(len(g.commands) for g in metadata.command_groups)
        summary = {
            "package": f"n8n-nodes-{cli_name}",
            "path": pkg_path,
            "resources": len(metadata.command_groups),
            "operations": total_ops,
            "credentials": len(metadata.credentials),
        }
        print_json(summary)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def nodes_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List previously generated n8n node packages.

    Example:
        n8n-cli-tool-node-converter nodes list
        n8n-cli-tool-node-converter nodes list --table
    """
    try:
        client = get_client()
        packages = client.list_generated()

        # Convert models to dicts for filtering
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
        n8n-cli-tool-node-converter nodes get brickowl
        n8n-cli-tool-node-converter nodes get brickowl --table
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


COMMAND_CREDENTIALS = {
    "generate": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
