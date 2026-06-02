"""Publisher commands for Awin CLI."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import apply_cli_filters, output_item, output_list


COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"],
    "get": ["personal_access_token"],
}

app = typer.Typer(help="Manage Awin publisher accounts", no_args_is_help=True)


@app.command("list")
def publishers_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List publisher accounts the authenticated user has access to."""
    try:
        items = get_client().list_publishers(filters=filter)
        items = items[:limit]
        output_list(
            items,
            table,
            properties,
            ["accountId", "accountName", "accountType", "userRole"],
            ["Account ID", "Account Name", "Type", "Role"],
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def publishers_get(
    publisher_id: str = typer.Argument(..., help="Publisher account id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one publisher account (filtered from the /accounts list)."""
    try:
        publishers = get_client().list_publishers()
        match = next(
            (p for p in publishers if str(p.accountId) == str(publisher_id)),
            None,
        )
        if match is None:
            raise typer.Exit(handle_error(
                ValueError(f"Publisher {publisher_id} not found in accessible accounts")
            ))
        output_item(match, table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
