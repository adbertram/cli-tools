"""CLI tools commands - list and inspect available CLI tools for node conversion."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="List and inspect available CLI tools for node conversion", no_args_is_help=True)


@app.command("list")
def tools_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List available CLI tools that can be converted to n8n nodes.

    Example:
        n8n nodes cli-tools list
        n8n nodes cli-tools list --table
        n8n nodes cli-tools list --limit 10
    """
    try:
        client = get_client()
        tools = client.list_tools()

        if filter:
            tools = apply_filters(tools, filter)

        tools = apply_limit(tools, limit)

        if properties:
            tools = apply_properties_filter(tools, properties)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(tools, fields, fields)
            else:
                print_table(
                    tools,
                    ["name", "description"],
                    ["Name", "Description"],
                )
        else:
            print_json(tools)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tools_get(
    name: str = typer.Argument(..., help="CLI tool name to inspect"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Inspect a CLI tool's metadata (command groups, commands, parameters, credentials).

    Example:
        n8n nodes cli-tools get brickowl
        n8n nodes cli-tools get shippo --table
    """
    try:
        client = get_client()
        metadata = client.get_tool(name)

        if table:
            # Summary view
            rows = []
            for group in metadata.command_groups:
                for cmd in group.commands:
                    param_count = len(cmd.parameters)
                    required = sum(1 for p in cmd.parameters if p.required)
                    rows.append({
                        "resource": group.name,
                        "operation": cmd.name,
                        "description": cmd.help_text or "",
                        "params": param_count,
                        "required": required,
                    })
            print_table(
                rows,
                ["resource", "operation", "description", "params", "required"],
                ["Resource", "Operation", "Description", "Params", "Required"],
            )
        else:
            print_json(metadata)

    except Exception as e:
        raise typer.Exit(handle_error(e))
