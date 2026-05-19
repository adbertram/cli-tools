"""Website/media property commands."""
from typing import List, Optional

import typer

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, output_list, read_json_body


COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"], "create": ["custom"], "update": ["custom"], "delete": ["custom"]}

app = typer.Typer(help="Manage websites and media properties", no_args_is_help=True)


@app.command("list")
def websites_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List websites/media properties."""
    try:
        output_list(get_client().list_websites(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def websites_get(website_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one website/media property."""
    try:
        output_item(get_client().get_website(website_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create")
def websites_create(
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a website/media property."""
    try:
        output_item(get_client().create_website(read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def websites_update(
    website_id: str,
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON request body file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Update a website/media property."""
    try:
        output_item(get_client().update_website(website_id, read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("delete")
def websites_delete(
    website_id: str,
    force: bool = typer.Option(False, "--force", "-F", help="Delete the website"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete a website/media property."""
    try:
        if not force:
            raise ClientError("Delete is destructive; rerun with --force to continue")
        output_item(get_client().delete_website(website_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
