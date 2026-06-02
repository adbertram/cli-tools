"""Cart commands for Instacart CLI."""
from typing import Optional

import typer

from ..client import get_client
from cli_tools_shared.output import handle_error, print_json, print_table

app = typer.Typer(help="Manage Instacart shopping cart", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def cart_default(
    ctx: typer.Context,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    store: Optional[str] = typer.Option(
        None, "--store", "-s", help="Filter by store name"
    ),
):
    """
    Show cart items across all stores.

    Examples:
        instacart cart
        instacart cart --table
        instacart cart --store ALDI
    """
    if ctx.invoked_subcommand is not None:
        return

    try:
        client = get_client()
        cart_data = client.get_cart_items(store_filter=store)

        if table:
            if not cart_data:
                typer.echo("No items in cart")
                return

            print_table(
                cart_data,
                ["store", "name", "qty", "price"],
                ["Store", "Item", "Qty", "Price"],
            )
        else:
            print_json(cart_data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def cart_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    store: Optional[str] = typer.Option(
        None, "--store", "-s", help="Filter by store name"
    ),
):
    """
    List all cart items.

    Examples:
        instacart cart list
        instacart cart list --table
        instacart cart list --store ALDI
    """
    try:
        client = get_client()
        cart_data = client.get_cart_items(store_filter=store)

        if table:
            if not cart_data:
                typer.echo("No items in cart")
                return

            print_table(
                cart_data,
                ["store", "name", "qty", "price"],
                ["Store", "Item", "Qty", "Price"],
            )
        else:
            print_json(cart_data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("summary")
def cart_summary(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show cart summary by store.

    Examples:
        instacart cart summary
        instacart cart summary --table
    """
    try:
        client = get_client()
        carts = client.get_carts()

        summary = []
        for cart in carts:
            summary.append({
                "store": cart.get("retailer", "-"),
                "item_count": cart.get("item_count", 0),
                "cart_id": cart.get("id"),
            })

        if table:
            if not summary:
                typer.echo("No active carts")
                return

            print_table(
                summary,
                ["store", "item_count"],
                ["Store", "Items"],
            )
        else:
            print_json(summary)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "list": [
        "custom"
    ],
    "summary": [
        "custom"
    ]
}
