"""Action, action item, update, and inquiry commands."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, output_list, read_json_body


COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"], "items": ["custom"], "item": ["custom"], "updates": ["custom"], "inquiries": ["custom"]}

app = typer.Typer(help="Manage actions and action support workflows", no_args_is_help=True)
updates_app = typer.Typer(help="Manage action updates", no_args_is_help=True)
inquiries_app = typer.Typer(help="Manage action inquiries", no_args_is_help=True)


@app.command("list")
def actions_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List actions."""
    try:
        output_list(get_client().list_actions(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def actions_get(action_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one action."""
    try:
        output_item(get_client().get_action(action_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("items")
def action_items(
    action_id: str,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List items for an action."""
    try:
        output_list(get_client().list_action_items(action_id, limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("item")
def action_item(action_id: str, sku: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one action item."""
    try:
        output_item(get_client().get_action_item(action_id, sku), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@updates_app.command("list")
def updates_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List action updates."""
    try:
        output_list(get_client().list_action_updates(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@updates_app.command("get")
def updates_get(update_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one action update."""
    try:
        output_item(get_client().get_action_update(update_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@inquiries_app.command("list")
def inquiries_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List action inquiries."""
    try:
        output_list(get_client().list_action_inquiries(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@inquiries_app.command("get")
def inquiries_get(inquiry_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one action inquiry."""
    try:
        output_item(get_client().get_action_inquiry(inquiry_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@inquiries_app.command("create")
def inquiries_create(
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create an action inquiry."""
    try:
        output_item(get_client().create_action_inquiry(read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


app.add_typer(updates_app, name="updates")
app.add_typer(inquiries_app, name="inquiries")
