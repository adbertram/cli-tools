"""Order operations preserve caller IDs and broker response bodies."""
from __future__ import annotations
from typing import List, Optional
import typer
from cli_tools_shared.output import command, print_json
from ..client import WebullClient, WebullError
from ..presentation import guard, render
import json
import sys
from pathlib import Path

app = typer.Typer(help="Inspect and manage orders", no_args_is_help=True)
COMMAND_CREDENTIALS = {name: ["custom"] for name in ("list", "open", "history", "get", "place", "replace", "cancel")}

def order_page(account, history, page_size, last_client_order_id, start_date, end_date, limit, filters, properties, table):
    body = WebullClient().orders(account, history=history, page_size=limit if limit is not None else page_size,
                                last_client_order_id=last_client_order_id, start_date=start_date, end_date=end_date)
    render(body, table=table, filters=filters, properties=properties)


@app.command("list")
@app.command("open")
@command
@guard
def open_orders(
    account: str,
    page_size: int = typer.Option(100, "--page-size", min=1, help="API page size"),
    last_client_order_id: Optional[str] = typer.Option(None, "--last-client-order-id", help="Exact API cursor"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", min=1, help="API page size; overrides --page-size"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Local field:op:value filter"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one page of working orders; caller follows the unchanged cursor."""
    order_page(account, False, page_size, last_client_order_id, None, None, limit, filter, properties, table)


@app.command("history")
@command
@guard
def order_history(
    account: str,
    page_size: int = typer.Option(100, "--page-size", min=1, help="API page size"),
    last_client_order_id: Optional[str] = typer.Option(None, "--last-client-order-id", help="Exact API cursor"),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="API start date, passed unchanged"),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="API end date, passed unchanged"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", min=1, help="API page size; overrides --page-size"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Local field:op:value filter"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one page of history with exact API cursor and date filters."""
    order_page(account, True, page_size, last_client_order_id, start_date, end_date, limit, filter, properties, table)


@app.command("get")
@command
@guard
def get_order(account: str, client_order_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get the full broker response for a client order ID."""
    render(WebullClient().order(account, client_order_id), table=table)


def read_orders(source):
    try:
        orders = json.loads(sys.stdin.read() if source == "-" else Path(source).read_text())
    except (ValueError, OSError):
        raise WebullError("validation", "orders-json must contain a JSON array of order objects.") from None
    if not isinstance(orders, list) or not orders or any(not isinstance(order, dict) for order in orders):
        raise WebullError("validation", "orders-json must contain a nonempty JSON array of order objects.")
    ids = [order.get("client_order_id") for order in orders]
    if any(not isinstance(cid, str) or not cid.strip() or len(cid) > 32 for cid in ids) or len(ids) != len(set(ids)):
        raise WebullError("validation", "Each order needs a unique nonempty client_order_id of at most 32 characters.")
    return orders


def mutation(action, account, orders_json, yes, dry_run, send_before_epoch_ms=None):
    if yes == dry_run:
        raise WebullError("validation", "Choose exactly one of --yes or --dry-run for order mutations.")
    orders = read_orders(orders_json)
    if dry_run:
        print_json({"dry_run": True, "action": action, "account_id": account, "new_orders": orders})
    else:
        print_json(WebullClient().mutate(action, account, orders, send_before_epoch_ms=send_before_epoch_ms))


@app.command("place")
@command
@guard
def place_order(account: str, orders_json: str = typer.Option(..., "--orders-json", help="JSON array file; - reads stdin"),
                yes: bool = typer.Option(False, "--yes", help="Send the broker request"),
                dry_run: bool = typer.Option(False, "--dry-run", help="Validate and print without sending"),
                send_before_epoch_ms: Optional[int] = typer.Option(None, "--send-before-epoch-ms", min=1, help="Refuse transport after this UTC epoch millisecond deadline")):
    """Place caller-defined orders once; never retry an uncertain write."""
    mutation("place", account, orders_json, yes, dry_run, send_before_epoch_ms)


@app.command("replace")
@command
@guard
def replace_order(account: str, orders_json: str = typer.Option(..., "--orders-json", help="JSON array file; - reads stdin"),
                  yes: bool = typer.Option(False, "--yes", help="Send the broker request"),
                  dry_run: bool = typer.Option(False, "--dry-run", help="Validate and print without sending"),
                  send_before_epoch_ms: Optional[int] = typer.Option(None, "--send-before-epoch-ms", min=1, help="Refuse transport after this UTC epoch millisecond deadline")):
    """Replace caller-defined orders once."""
    mutation("replace", account, orders_json, yes, dry_run, send_before_epoch_ms)


@app.command("cancel")
@command
@guard
def cancel_order(account: str, client_order_id: str,
                 yes: bool = typer.Option(False, "--yes", help="Send the broker request"),
                 dry_run: bool = typer.Option(False, "--dry-run", help="Print without sending")):
    """Cancel one broker order by caller-defined client order ID."""
    if yes == dry_run:
        raise WebullError("validation", "Choose exactly one of --yes or --dry-run for order mutations.")
    if dry_run:
        print_json({"dry_run": True, "action": "cancel", "account_id": account, "client_order_id": client_order_id})
    else:
        print_json(WebullClient().cancel(account, client_order_id))


