"""Board commands for Pinterest CLI."""

COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
}

from typing import List, Optional

import typer

from cli_tools_shared.output import print_json, print_table, command

from ..client import get_client
from ._common import (
    apply_properties_to_item,
    apply_properties_to_items,
    detail_rows,
    format_timestamp_columns,
)

app = typer.Typer(help="Manage Pinterest boards", no_args_is_help=True)


@app.command("list")
@command
def boards_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(25, "--limit", "-l", min=1, help="Maximum number of boards to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (for example privacy:eq:SECRET)",
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
    """List Pinterest boards for the authenticated user."""
    boards = get_client().list_boards(limit=limit, filters=filter, ad_account_id=ad_account_id)

    if properties:
        rows = apply_properties_to_items(boards, properties)
        if table:
            fields = [part.strip() for part in properties.split(",") if part.strip()]
            print_table(format_timestamp_columns(rows), fields, fields)
            return
        print_json(rows)
        return

    if table:
        rows = format_timestamp_columns(
            [
                {
                    "id": board.id,
                    "name": board.name,
                    "privacy": board.privacy,
                    "follower_count": board.follower_count,
                    "created_at": board.created_at,
                }
                for board in boards
            ]
        )
        print_table(
            rows,
            ["id", "name", "privacy", "follower_count", "created_at"],
            ["ID", "Name", "Privacy", "Followers", "Created"],
        )
        return

    print_json(boards)


@app.command("get")
@command
def boards_get(
    board_id: str = typer.Argument(..., help="Pinterest board ID"),
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
    """Get a specific Pinterest board by ID."""
    board = get_client().get_board(board_id, ad_account_id=ad_account_id)

    if properties:
        selected = apply_properties_to_item(board, properties)
        if table:
            fields = [part.strip() for part in properties.split(",") if part.strip()]
            print_table(format_timestamp_columns([selected]), fields, fields)
            return
        print_json(selected)
        return

    if table:
        print_table(detail_rows(board), ["field", "value"], ["Field", "Value"])
        return

    print_json(board)
