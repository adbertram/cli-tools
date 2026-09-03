"""Main entry point for TraineeDigital CLI."""

import typer
from typing import List, Optional

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import ClientError, get_client
from .config import get_config
from .filters import validate_order_filters

COLUMNS = {
    "id": "ID",
    "title": "Title",
    "category": "Category",
    "pay": "Pay",
    "unit": "Unit",
    "volume": "Volume",
    "deadline": "Deadline",
    "posted": "Posted",
}

app = create_app(
    name="trainee-digital",
    help="CLI interface for trainee.digital (browser session, worker side)",
    version=__version__,
)
tasks_app = typer.Typer(help="Manage trainee.digital worker orders", no_args_is_help=True)


def _validate(filters: Optional[List[str]]) -> None:
    try:
        validate_order_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _emit_list(rows: List[dict], table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info("No orders found.")
        return
    columns = fields or list(COLUMNS)
    headers = fields or list(COLUMNS.values())
    print_table(rows, columns, headers)


def _emit_detail(row: dict, table: bool, properties: Optional[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if not table:
        print_json(row)
        return
    if fields:
        print_table([row], fields, fields)
        return
    print_table(
        [{"field": key, "value": value} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


@tasks_app.command("list")
@command
def tasks_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of orders"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., category:eq:Fintech)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """List the open annotation orders on the trainee.digital order feed."""
    _validate(filter)
    client = get_client()
    try:
        rows = client.list_tasks(limit=limit)
        if filter:
            rows = apply_filters(rows, filter)
        _emit_list(rows, table, properties)
    finally:
        client.close()


@tasks_app.command("get")
@command
def tasks_get(
    order_id: str = typer.Argument(..., help="Order id (from 'tasks list' output)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get the full detail for a single order."""
    client = get_client()
    try:
        row = client.get_task(order_id)
        _emit_detail(row, table, properties)
    finally:
        client.close()


@tasks_app.command("apply")
@command
def tasks_apply(
    order_id: str = typer.Argument(..., help="Order id (from 'tasks list' output)"),
    confirm: bool = typer.Option(False, "--confirm", help="Unused: applying is always refused"),
):
    """Apply to an order.

    ALWAYS refused: the MicroWorker project only discovers and reports tasks.
    Applying is Adam's decision for the exact task in the conversation, and
    trainee.digital applies are gated behind the free quality review anyway.
    """
    raise ClientError(
        f"Refusing to apply to trainee.digital order {order_id!r}: MicroWorker "
        "never applies to tasks; applying is Adam's decision in the conversation."
    )


app.add_typer(tasks_app, name="tasks")
app.add_typer(create_auth_app(get_config, tool_name="trainee-digital"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
