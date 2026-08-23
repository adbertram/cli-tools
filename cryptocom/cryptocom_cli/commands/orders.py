"""Private order commands for Crypto.com Exchange."""
COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "details": [
        "custom"
    ],
    "cancel": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}

from decimal import Decimal, InvalidOperation
from typing import List, Optional

import typer

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command

from ..client import get_client
from ._display import emit

app = typer.Typer(help="Place and manage trading orders", no_args_is_help=True)

ORDER_COLUMNS = [
    "order_id",
    "instrument_name",
    "side",
    "order_type",
    "quantity",
    "limit_price",
    "status",
]

SIDE_VALUES = {
    "BUY": "BUY",
    "SELL": "SELL",
}

ORDER_TYPE_VALUES = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
}

TIME_IN_FORCE_ALIASES = {
    "GTC": "GOOD_TILL_CANCEL",
    "IOC": "IMMEDIATE_OR_CANCEL",
    "FOK": "FILL_OR_KILL",
    "GOOD_TILL_CANCEL": "GOOD_TILL_CANCEL",
    "IMMEDIATE_OR_CANCEL": "IMMEDIATE_OR_CANCEL",
    "FILL_OR_KILL": "FILL_OR_KILL",
}


def _resolve_choice(value: str, choices: dict, label: str) -> str:
    """Map a case-insensitive CLI choice to its Exchange API value."""
    resolved = choices.get(value.strip().upper())
    if resolved is None:
        valid = ", ".join(sorted(choices))
        raise ClientError(f"Invalid {label}: {value}. Valid values: {valid}")
    return resolved


def _resolve_time_in_force(value: Optional[str]) -> Optional[str]:
    """Map a --tif alias or full name to the Exchange API value."""
    if value is None:
        return None
    return _resolve_choice(value, TIME_IN_FORCE_ALIASES, "time in force")


def _validated_amount(value: str, label: str) -> str:
    """Validate a decimal CLI amount and return the exact text."""
    text = value.strip()
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ClientError(f"{label} must be a decimal number, got: {value}")
    if number <= 0:
        raise ClientError(f"{label} must be positive, got: {value}")
    return text


@app.command("create")
@command
def orders_create(
    symbol: str = typer.Option(..., "--symbol", "-s", help="Instrument name (e.g., BTC_USD)"),
    side: str = typer.Option(..., "--side", help="Order side: buy or sell (case-insensitive)"),
    quantity: str = typer.Option(..., "--quantity", "-q", help="Order quantity in base currency"),
    price: Optional[str] = typer.Option(None, "--price", help="Limit price (required for --type limit)"),
    order_type: str = typer.Option("LIMIT", "--type", help="Order type: MARKET or LIMIT"),
    tif: Optional[str] = typer.Option(None, "--tif", help="Time in force: GTC, IOC, FOK (default GOOD_TILL_CANCEL)"),
    client_oid: Optional[str] = typer.Option(None, "--client-oid", help="Optional client order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create a new order."""
    order = get_client().create_order(
        instrument_name=symbol.strip().upper(),
        side=_resolve_choice(side, SIDE_VALUES, "side"),
        quantity=_validated_amount(quantity, "Quantity"),
        order_type=_resolve_choice(order_type, ORDER_TYPE_VALUES, "order type"),
        limit_price=_validated_amount(price, "Price") if price is not None else None,
        time_in_force=_resolve_time_in_force(tif),
        client_oid=client_oid,
    )
    emit(order, table=table, columns=["order_id"], properties=properties)


def _emit_order_detail(order_id: str, table: bool, properties: Optional[str]):
    """Fetch one order by ID and emit it."""
    order = get_client().get_order_detail(order_id)
    emit(order, table=table, columns=ORDER_COLUMNS, properties=properties)


@app.command("get")
@command
def orders_get(
    order_id: str = typer.Argument(..., help="Order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one order by ID."""
    _emit_order_detail(order_id, table=table, properties=properties)


@app.command("details")
@command
def orders_details(
    order_id: str = typer.Argument(..., help="Order ID (alias of 'orders get')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one order by ID (alias of get)."""
    _emit_order_detail(order_id, table=table, properties=properties)


@app.command("cancel")
@command
def orders_cancel(
    order_id: str = typer.Argument(..., help="Order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Cancel one order by ID."""
    result = get_client().cancel_order(order_id)
    emit(result, table=table, columns=["order_id"], properties=properties)


@app.command("list")
@command
def orders_list(
    instrument_name: Optional[str] = typer.Option(None, "--instrument-name", "-i", help="Instrument name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of open orders to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List open orders."""
    orders = get_client().list_open_orders(
        instrument_name=instrument_name,
        limit=limit,
        filters=filter,
    )
    emit(orders, table=table, columns=ORDER_COLUMNS, properties=properties)
