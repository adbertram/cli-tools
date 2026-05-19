"""Health check commands."""
from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_limit,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import handle_error, print_error, print_json, print_table

from ..client import get_client

app = typer.Typer(help="Run Cody bridge health checks", no_args_is_help=True)


@app.command("list")
def list_checks(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of checks"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List Cody bridge health checks."""
    try:
        if filter:
            validate_filters(filter)
        rows = [item.model_dump() for item in get_client().list_checks()]
        rows = apply_filters(rows, filter)
        rows = apply_limit(rows, limit)
        rows = apply_properties_filter(rows, properties)
        if table:
            columns = properties.split(",") if properties else ["id", "name", "ok", "detail"]
            print_table(rows, columns, [column.replace("_", " ").title() for column in columns])
        else:
            print_json(rows)
    except FilterValidationError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_check(
    check_id: str = typer.Argument(..., help="Health check ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a single Cody bridge health check by ID."""
    try:
        rows = [item.model_dump() for item in get_client().list_checks()]
        matches = [row for row in rows if row["id"] == check_id]
        if len(matches) != 1:
            print_error(f"Check not found: {check_id}")
            raise typer.Exit(1)
        if table:
            print_table(matches, ["id", "name", "ok", "detail"], ["ID", "Name", "OK", "Detail"])
        else:
            print_json(matches[0])
    except Exception as e:
        raise typer.Exit(handle_error(e))
