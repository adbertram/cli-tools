"""Prescription commands for CVS CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

import typer
from typing import List, Optional

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter


app = typer.Typer(help="Manage prescriptions", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


DEFAULT_TABLE_COLS = [
    "id",
    "drugInfo.drug.name",
    "rxStatus.statusText",
    "patientFirstName",
    "lastRefillDate",
    "quantity",
]
DEFAULT_TABLE_HEADERS = [
    "ID",
    "Drug",
    "Status",
    "Patient",
    "Last Refill",
    "Qty",
]


def _build_table_rows(items, cols):
    """Build flat table rows from items using dot-notation columns."""
    rows = []
    for item in items:
        row = {}
        for col in cols:
            row[col] = extract_field(item, col)
        rows.append(row)
    return rows


@app.command("list")
def prescriptions_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List all prescriptions."""
    try:
        client = get_client()
        items = client.list_prescriptions()
        items = [i.model_dump() for i in items]
        if filter:
            items = apply_filters(items, filter)
        items = apply_limit(items, limit)
        if properties:
            items = apply_properties_filter(items, properties)
        if table:
            if properties:
                cols = [c.strip() for c in properties.split(",")]
                headers = [c.split(".")[-1] for c in cols]
            else:
                cols = DEFAULT_TABLE_COLS
                headers = DEFAULT_TABLE_HEADERS
            display = _build_table_rows(items, cols)
            print_table(display, cols, headers)
        else:
            print_json(items)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def prescriptions_get(
    rx_id: str = typer.Argument(..., help="Prescription ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a specific prescription."""
    try:
        client = get_client()
        item = client.get_prescription(rx_id)
        data = item.model_dump()
        if table:
            print_table([data], list(data.keys()), list(data.keys()))
        else:
            print_json(data)
    except Exception as e:
        raise typer.Exit(handle_error(e))
