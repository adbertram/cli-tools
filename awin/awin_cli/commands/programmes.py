"""Programme (advertiser) commands for Awin CLI."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, output_list


COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"],
    "get": ["personal_access_token"],
}

app = typer.Typer(help="Manage Awin advertiser programmes", no_args_is_help=True)


@app.command("list")
def programmes_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Awin publisher id (defaults to AWIN_PUBLISHER_ID)"),
    relationship: str = typer.Option("joined", "--relationship", "-r", help="joined | notjoined | pending"),
):
    """List advertiser programmes for the current publisher."""
    try:
        items = get_client().list_programmes(
            publisher_id=publisher_id,
            relationship=relationship,
            limit=limit,
            filters=filter,
        )
        output_list(
            items,
            table,
            properties,
            ["id", "name", "status", "primarySector"],
            ["ID", "Name", "Status", "Sector"],
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def programmes_get(
    programme_id: str = typer.Argument(..., help="Advertiser programme id"),
    publisher_id: Optional[str] = typer.Option(None, "--publisher-id", help="Awin publisher id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one advertiser programme by id."""
    try:
        item = get_client().get_programme(publisher_id, programme_id)
        output_item(item, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
