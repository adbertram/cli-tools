"""Order commands. Placing or cancelling refuses without --yes or --dry-run, and production needs --allow-production."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "place": ["no_auth"],
    "cancel": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.output import command, print_json

from ..client import TIME_IN_FORCE, build_order_body, identifier, resolve_env
from ._common import (
    DEMO_OPTION,
    ENV_OPTION,
    FILTER_OPTION,
    LIMIT_OPTION,
    PROPERTIES_OPTION,
    TABLE_OPTION,
    check_filters,
    emit_record,
    emit_rows,
    open_client,
)

app = typer.Typer(help="List, place and cancel orders", no_args_is_help=True)

COLUMNS = ["order_id", "ticker", "outcome_side", "status", "yes_price_dollars", "initial_count_fp", "fill_count_fp", "remaining_count_fp"]

# Filters whose field means the same thing in the output and the API become API parameters.
FILTER_MAP = (
    FilterMap()
    .register_api_translator("ticker", lambda op, value: {"ticker": value} if op == "eq" else {})
    .register_api_translator("event_ticker", lambda op, value: {"event_ticker": value} if op == "eq" else {})
    .register_api_translator("status", lambda op, value: {"status": value} if op == "eq" else {})
)


def _guard(action: str, yes: bool, dry_run: bool, allow_production: bool, environment: str) -> None:
    """Refuse real-money changes without explicit confirmation."""
    if not (yes or dry_run):
        raise ClientError(f"Refusing to {action} without --yes or --dry-run")
    if environment == "prod" and not dry_run and not allow_production:
        raise ClientError(f"Refusing to {action} on production without --allow-production. Use --demo for the demo exchange.")


@app.command("list")
@command
def orders_list(
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Only orders in this market"),
    status: Optional[str] = typer.Option(None, "--status", help="resting, canceled or executed"),
    limit: int = LIMIT_OPTION,
    filter: Optional[List[str]] = FILTER_OPTION,
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """List orders."""
    check_filters(filter)
    params = {**FILTER_MAP.to_api_params(filter or []), **{k: v for k, v in {"ticker": ticker, "status": status}.items() if v}}
    with open_client(env, demo, auth=True) as client:
        rows = client.list_orders(limit=limit, **params)
    emit_rows(rows, filter, table, properties, COLUMNS, "No orders found.")


@app.command("get")
@command
def orders_get(
    order_id: str = typer.Argument(..., help="Order ID"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Get one order."""
    with open_client(env, demo, auth=True) as client:
        emit_record(client.get_order(order_id), table, properties)


@app.command("place")
@command
def orders_place(
    ticker: str = typer.Argument(..., help="Market ticker"),
    outcome: str = typer.Option(..., "--outcome", "-o", help="yes or no (BTC 15m: yes = up, no = down)"),
    count: str = typer.Option(..., "--count", "-c", help="Contracts, up to 2 decimals"),
    price: str = typer.Option(..., "--price", help="Price of the chosen outcome in dollars, for example 0.55"),
    tif: str = typer.Option("gtc", "--tif", help=f"Time in force: {', '.join(TIME_IN_FORCE)}"),
    post_only: bool = typer.Option(False, "--post-only", help="Reject instead of crossing the book"),
    reduce_only: bool = typer.Option(False, "--reduce-only", help="Only reduce an existing position (requires --tif ioc)"),
    expiration_ts: Optional[int] = typer.Option(None, "--expiration-ts", help="Unix seconds when the order expires (requires --tif gtc)"),
    client_order_id: Optional[str] = typer.Option(None, "--client-order-id", help="Client order ID (default: generated UUID)"),
    stp: str = typer.Option("taker_at_cross", "--stp", help="Self-trade prevention: taker_at_cross or maker"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm placing the order"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
    allow_production: bool = typer.Option(False, "--allow-production", help="Allow a real-money order on the production exchange"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Place a limit order."""
    environment = resolve_env(env, demo)
    _guard("place order", yes, dry_run, allow_production, environment)
    body = build_order_body(
        ticker, outcome, count, price, time_in_force=tif, post_only=post_only, reduce_only=reduce_only,
        expiration_ts=expiration_ts, client_order_id=client_order_id, self_trade_prevention=stp,
    )
    if dry_run:
        print_json({"dry_run": True, "environment": environment, "method": "POST", "path": "/portfolio/events/orders", "body": body})
        return
    with open_client(environment, False, auth=True) as client:
        emit_record(client.create_order(body), table, properties)


@app.command("cancel")
@command
def orders_cancel(
    order_id: str = typer.Argument(..., help="Order ID"),
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Market ticker (lets Kalshi route the cancel to the right shard)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm cancelling the order"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
    allow_production: bool = typer.Option(False, "--allow-production", help="Allow cancelling on the production exchange"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Cancel an order."""
    environment = resolve_env(env, demo)
    _guard("cancel order", yes, dry_run, allow_production, environment)
    if dry_run:
        print_json({"dry_run": True, "environment": environment, "method": "DELETE", "path": f"/portfolio/events/orders/{identifier(order_id, 'order ID')}", "params": {"market_ticker": identifier(ticker, "ticker") if ticker else None}})
        return
    with open_client(environment, False, auth=True) as client:
        emit_record(client.cancel_order(order_id, ticker), table, properties)
