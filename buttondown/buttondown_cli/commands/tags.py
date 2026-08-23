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

from cli_tools_shared.output import command

from ..client import get_client
from .common import confirm_delete, emit


app = typer.Typer(help="Manage tags", no_args_is_help=True)


@app.command("list")
@command
def tags_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tags"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List tags."""
    # filter_map translation happens in the client with Buttondown query params.
    tags = get_client().list_tags(limit=limit, filters=filter)
    emit(tags, table, properties, ["id", "name", "color", "subscriber_editable"])


@app.command("get")
@command
def tags_get(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a tag."""
    emit(get_client().get_tag(tag_id), table, properties, ["id", "name", "color"])


@app.command("create")
@command
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
    tag = get_client().create_tag(
        name=name,
        color=color,
        description=description,
        public_description=public_description,
        subscriber_editable=subscriber_editable,
    )
    emit(tag, table, properties, ["id", "name", "color"])


@app.command("update")
@command
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
    tag = get_client().update_tag(
        tag_id,
        name=name,
        color=color,
        description=description,
        public_description=public_description,
        subscriber_editable=subscriber_editable,
    )
    emit(tag, table, properties, ["id", "name", "color"])


@app.command("delete")
@command
def tags_delete(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    force: bool = typer.Option(False, "--force", "-F", help="Delete without confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete a tag."""
    confirm_delete("tag", tag_id, force)
    emit(get_client().delete_tag(tag_id), table, None, ["ok", "action", "id"])


@app.command("analytics")
@command
def tags_analytics(
    tag_id: str = typer.Argument(..., help="Tag ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get tag analytics."""
    emit(get_client().get_tag_analytics(tag_id), table, properties, ["created_subscribers", "open_rate", "click_rate"])
