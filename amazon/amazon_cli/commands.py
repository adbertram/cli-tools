"""Amazon order evidence commands."""

from __future__ import annotations

from typing import List, Optional

import typer

from cli_tools_shared.filters import FilterValidationError, apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from .client import get_client

app = typer.Typer(help="Inspect Amazon order evidence", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "match": ["browser_session"],
}

COLUMNS = ["id", "line", "text", "score", "matched_amount", "matched_terms"]


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or [column for column in COLUMNS if column in rows[0]]
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


@app.command("list")
@command
def orders_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum visible text lines"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List visible evidence lines from Amazon order history."""
    _validate(filter)
    client = get_client()
    try:
        rows = client.list_orders(limit=limit)
        if filter:
            rows = apply_filters(rows, filter)
        _render(rows, table, properties, "No Amazon order evidence found.")
    finally:
        client.close()


@app.command("get")
@command
def orders_get(
    record_id: str = typer.Argument(..., help="Evidence line id from orders list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one Amazon order evidence line."""
    client = get_client()
    try:
        row = client.get_order_line(record_id)
        if table:
            columns = _property_fields(properties) or list(row.keys())
            print_table([row], columns, [column.replace("_", " ").title() for column in columns])
        elif properties:
            print_json(apply_properties_filter([row], properties)[0])
        else:
            print_json(row)
    finally:
        client.close()


@app.command("match")
@command
def orders_match(
    amount: Optional[str] = typer.Option(None, "--amount", "-a", help="Transaction amount to match"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Transaction date or posting date to match"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Order search text"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum matches"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Find Amazon order evidence matching amount, date, or query."""
    _validate(filter)
    client = get_client()
    try:
        rows = client.match_order(amount=amount, date=date, query=query, limit=limit)
        if filter:
            rows = apply_filters(rows, filter)
        _render(rows, table, properties, "No matching Amazon order evidence found.")
    finally:
        client.close()
