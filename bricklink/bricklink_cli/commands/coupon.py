"""Coupon commands for Bricklink CLI."""
COMMAND_CREDENTIALS = {
    "create": ["oauth"],
    "delete": ["oauth"],
    "get": ["oauth"],
    "list": ["oauth"],
}

import typer
from typing import Optional, List

from ..client import get_client
from ..display import print_detail, print_list
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from cli_tools_shared.output import print_json, print_success, handle_error

app = typer.Typer(help="Manage coupons", no_args_is_help=True)


# ==================== Default Table Columns ====================

COUPON_LIST_COLUMNS = ["coupon_id", "buyer_name", "discount_type", "discount_rate", "status", "date_expire"]
COUPON_LIST_HEADERS = ["ID", "Buyer", "Disc Type", "Disc Rate", "Status", "Expires"]


# ==================== Commands ====================


@app.command("list")
def coupon_list(
    direction: Optional[str] = typer.Option(None, "--direction", "-d", help="'out' (issued) or 'in' (received)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="O=open, S=redeemed, D=denied, E=expired"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields to include"),
):
    """
    List coupons.

    Examples:
        bricklink coupon list
        bricklink coupon list --direction out
        bricklink coupon list --status O --table
        bricklink coupon list --filter "buyer_name:contains:John"
    """
    try:
        client = get_client()
        raw = client.list_coupons(direction=direction, status=status)
        data = raw

        if filter:
            data = apply_filters(data, filter)
        if properties:
            data = apply_properties_filter(data, properties)
        data = apply_limit(data, limit)

        print_list(data, table, properties, COUPON_LIST_COLUMNS, COUPON_LIST_HEADERS)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def coupon_get(
    coupon_id: str = typer.Argument(..., help="Coupon ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get coupon details by ID.

    Examples:
        bricklink coupon get 12345
        bricklink coupon get 12345 --table
    """
    try:
        client = get_client()
        data = client.get_coupon(coupon_id)
        print_detail(data, table)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def coupon_create(
    buyer: str = typer.Argument(..., help="Buyer username"),
    discount_type: str = typer.Option("F", "--type", help="F=fixed amount, S=percentage"),
    discount_rate: str = typer.Option(..., "--rate", "-r", help="Discount amount or percentage"),
    max_discount: Optional[str] = typer.Option(None, "--max", help="Max discount amount (for percentage type)"),
    expires: Optional[str] = typer.Option(None, "--expires", help="Expiry date (YYYY-MM-DD)"),
    remarks: Optional[str] = typer.Option(None, "--remarks", help="Coupon remarks/description"),
):
    """
    Create a coupon for a buyer.

    Examples:
        bricklink coupon create some_user --rate 5.00
        bricklink coupon create some_user --type S --rate 10 --max 20.00
        bricklink coupon create some_user --rate 3.00 --expires 2025-12-31 --remarks "Apology for missing part"
    """
    try:
        client = get_client()
        coupon_data = {
            "buyer_name": buyer,
            "discount_type": discount_type,
            "discount_rate": discount_rate,
        }

        if max_discount is not None:
            coupon_data["max_discount_amount"] = max_discount
        if expires is not None:
            coupon_data["date_expire"] = expires
        if remarks is not None:
            coupon_data["remarks"] = remarks

        result = client.create_coupon(coupon_data)
        print_success(f"Coupon created for {buyer}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def coupon_delete(
    coupon_id: str = typer.Argument(..., help="Coupon ID"),
):
    """
    Delete a coupon.

    Examples:
        bricklink coupon delete 12345
    """
    try:
        client = get_client()
        result = client.delete_coupon(coupon_id)
        print_success(f"Coupon {coupon_id} deleted")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
