"""Canvas management commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}

import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack canvases")


@app.command("list")
def list_canvases(
    channel_id: Optional[str] = typer.Argument(
        None, help="Channel ID to list canvases for (optional, lists all if not specified)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of canvases"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List canvases in the workspace or a specific channel.

    Example:
        slack canvas list --table
        slack canvas list C1234567890 --table
        slack canvas list --limit 50
    """
    try:
        client = get_client()
        response = client.list_canvases(channel=channel_id, count=limit)
        canvases = response.get("files", [])

        # Apply client-side filters
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))
            canvases = apply_filters(canvases, filter_)

        if properties:
            canvases = apply_properties_filter(canvases, properties)

        if table:
            from datetime import datetime

            table_data = [
                {
                    "id": c.get("id"),
                    "title": c.get("title", c.get("name", "Untitled")),
                    "created": datetime.fromtimestamp(c.get("created", 0)).strftime("%Y-%m-%d %H:%M")
                    if c.get("created")
                    else "",
                    "updated": datetime.fromtimestamp(c.get("updated", 0)).strftime("%Y-%m-%d %H:%M")
                    if c.get("updated")
                    else "",
                    "user": c.get("user", ""),
                }
                for c in canvases
            ]
            columns = ["id", "title", "created", "updated", "user"]
            headers = ["ID", "Title", "Created", "Updated", "User"]
            print_table(table_data, columns, headers)
        else:
            print_json({"canvases": canvases, "count": len(canvases)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_canvas(
    canvas_id: str = typer.Argument(..., help="Canvas ID (e.g., F1234567890)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    raw_html: bool = typer.Option(False, "--html", help="Output raw HTML instead of text"),
):
    """
    Get canvas content.

    Example:
        slack canvas get F1234567890
        slack canvas get F1234567890 --table
        slack canvas get F1234567890 --html
    """
    try:
        client = get_client()

        response = client.get_canvas_content(canvas_id=canvas_id)

        result = {
            "canvas_id": canvas_id,
            "title": response.get("title"),
            "content": response.get("content"),
        }

        if raw_html:
            result["html"] = response.get("html")

        if table:
            # For table output, show title and content preview
            content = response.get("content", "")
            preview = content[:200] + "..." if len(content) > 200 else content
            table_data = [
                {
                    "canvas_id": canvas_id,
                    "title": response.get("title", ""),
                    "content_preview": preview,
                }
            ]
            print_table(
                table_data,
                ["canvas_id", "title", "content_preview"],
                ["Canvas ID", "Title", "Content Preview"],
            )
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
