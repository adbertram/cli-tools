"""Pin commands for Pinterest CLI."""

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

app = typer.Typer(help="Manage Pinterest pins", no_args_is_help=True)


@app.command("list")
@command
def pins_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(25, "--limit", "-l", min=1, help="Maximum number of pins to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (for example board_owner.username:contains:brand)",
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
    """List Pinterest pins for the authenticated user."""
    pins = get_client().list_pins(limit=limit, filters=filter, ad_account_id=ad_account_id)

    if properties:
        rows = apply_properties_to_items(pins, properties)
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
                    "id": pin.id,
                    "title": pin.title,
                    "board_id": pin.board_id,
                    "creative_type": pin.creative_type,
                    "created_at": pin.created_at,
                }
                for pin in pins
            ]
        )
        print_table(
            rows,
            ["id", "title", "board_id", "creative_type", "created_at"],
            ["ID", "Title", "Board ID", "Creative Type", "Created"],
        )
        return

    print_json(pins)


@app.command("get")
@command
def pins_get(
    pin_id: str = typer.Argument(..., help="Pinterest pin ID"),
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
    """Get a specific Pinterest pin by ID."""
    pin = get_client().get_pin(pin_id, ad_account_id=ad_account_id)

    if properties:
        selected = apply_properties_to_item(pin, properties)
        if table:
            fields = [part.strip() for part in properties.split(",") if part.strip()]
            print_table(format_timestamp_columns([selected]), fields, fields)
            return
        print_json(selected)
        return

    if table:
        print_table(detail_rows(pin), ["field", "value"], ["Field", "Value"])
        return

    print_json(pin)
