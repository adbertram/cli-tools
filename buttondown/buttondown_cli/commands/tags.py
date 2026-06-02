"""Tag commands."""
COMMAND_CREDENTIALS = {
    "analytics": [
        "api_key"
    ],
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}

from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from .common import confirm_delete, emit


app = typer.Typer(help="Manage tags", no_args_is_help=True)


@app.command("list")
def tags_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tags"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List tags."""
    try:
        # filter_map translation happens in the client with Buttondown query params.
        tags = get_client().list_tags(limit=limit, filters=filter)
        emit(tags, table, properties, ["id", "name", "color", "subscriber_editable"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def tags_get(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a tag."""
    try:
        emit(get_client().get_tag(tag_id), table, properties, ["id", "name", "color"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create")
def tags_create(
    name: str = typer.Option(..., "--name", "-n", help="Tag name"),
    color: str = typer.Option(..., "--color", "-c", help="Hex color"),
    description: Optional[str] = typer.Option(None, "--description", help="Internal description"),
    public_description: Optional[str] = typer.Option(None, "--public-description", help="Subscriber-facing description"),
    subscriber_editable: Optional[bool] = typer.Option(None, "--subscriber-editable/--not-subscriber-editable", help="Subscriber editability"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create a tag."""
    try:
        tag = get_client().create_tag(
            name=name,
            color=color,
            description=description,
            public_description=public_description,
            subscriber_editable=subscriber_editable,
        )
        emit(tag, table, properties, ["id", "name", "color"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def tags_update(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Tag name"),
    color: Optional[str] = typer.Option(None, "--color", "-c", help="Hex color"),
    description: Optional[str] = typer.Option(None, "--description", help="Internal description"),
    public_description: Optional[str] = typer.Option(None, "--public-description", help="Subscriber-facing description"),
    subscriber_editable: Optional[bool] = typer.Option(None, "--subscriber-editable/--not-subscriber-editable", help="Subscriber editability"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Update a tag."""
    try:
        tag = get_client().update_tag(
            tag_id,
            name=name,
            color=color,
            description=description,
            public_description=public_description,
            subscriber_editable=subscriber_editable,
        )
        emit(tag, table, properties, ["id", "name", "color"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("delete")
def tags_delete(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    force: bool = typer.Option(False, "--force", "-F", help="Delete without confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete a tag."""
    try:
        confirm_delete("tag", tag_id, force)
        emit(get_client().delete_tag(tag_id), table, None, ["ok", "action", "id"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("analytics")
def tags_analytics(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get tag analytics."""
    try:
        emit(get_client().get_tag_analytics(tag_id), table, properties, ["created_subscribers", "open_rate", "click_rate"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
