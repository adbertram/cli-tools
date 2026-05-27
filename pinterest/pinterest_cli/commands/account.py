"""Account commands for Pinterest CLI."""

COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
}

import typer

from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, command

from ..client import get_client
from ._common import apply_properties_to_item, apply_properties_to_items, detail_rows

app = typer.Typer(help="Inspect the authenticated Pinterest account", no_args_is_help=True)


@app.command("list")
@command
def account_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(1, "--limit", "-l", min=1, help="Maximum number of accounts to return"),
    filter: list[str] | None = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: str | None = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
    ad_account_id: str | None = typer.Option(
        None,
        "--ad-account-id",
        help="Pinterest ad account ID for shared business access requests",
    ),
):
    """List the authenticated Pinterest account as a single-item collection."""
    account = get_client().get_user_account(ad_account_id=ad_account_id)
    rows = [account.model_dump(mode="json")]

    if filter:
        rows = apply_filters(rows, filter)

    if properties and rows:
        rows = apply_properties_to_items(rows, properties)

    if table:
        if properties:
            fields = [part.strip() for part in properties.split(",") if part.strip()]
            print_table(rows, fields, fields)
            return
        print_table(rows, ["id", "username", "account_type", "board_count"], ["ID", "Username", "Type", "Boards"])
        return

    print_json(rows[:limit])


@app.command("get")
@command
def account_get(
    account_id: str | None = typer.Argument(
        None,
        help="Authenticated Pinterest account ID to validate against the current account",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: str | None = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
    ad_account_id: str | None = typer.Option(
        None,
        "--ad-account-id",
        help="Pinterest ad account ID for shared business access requests",
    ),
):
    """Get the authenticated Pinterest user account."""
    account = get_client().get_user_account(ad_account_id=ad_account_id)
    if account_id is not None and str(account.id) != str(account_id):
        raise typer.BadParameter(
            f"Authenticated account id is {account.id}; received {account_id}."
        )

    if properties:
        selected = apply_properties_to_item(account, properties)
        if table:
            fields = [part.strip() for part in properties.split(",") if part.strip()]
            print_table([selected], fields, fields)
            return
        print_json(selected)
        return

    if table:
        print_table(detail_rows(account), ["field", "value"], ["Field", "Value"])
        return

    print_json(account)
