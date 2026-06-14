"""Project commands for Jira CLI."""

from typing import List, Optional

import typer
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import command, print_error, print_json, print_table

from ..client import get_client
from ..config import OAUTH_3LO_AUTH_TYPE

COMMAND_CREDENTIALS = {
    "list": [OAUTH_3LO_AUTH_TYPE, "custom"],
    "get": [OAUTH_3LO_AUTH_TYPE, "custom"],
}

LIST_COLUMNS = ["key", "name", "project_type", "style", "category", "lead"]

app = typer.Typer(help="Manage Jira projects", no_args_is_help=True)


def _properties(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    fields = [field.strip() for field in value.split(",") if field.strip()]
    return fields or None


def _select_fields(rows: List[dict], properties: Optional[str]) -> List[dict]:
    fields = _properties(properties)
    if fields is None:
        return rows
    return [{field: row.get(field) for field in fields} for row in rows]


def _print_rows(rows: List[dict], *, table: bool, properties: Optional[str], columns: List[str]) -> None:
    rows = _select_fields(rows, properties)
    if table:
        selected_columns = _properties(properties) or columns
        print_table(rows, selected_columns, [column.replace("_", " ").title() for column in selected_columns])
        return
    print_json(rows)


def _validate_filters(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc


@app.command("list")
@command
def list_projects(
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum number of projects"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter projects (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    query: Optional[str] = typer.Option(None, "--query", help="Free-text Jira project search"),
):
    """List Jira projects."""
    _validate_filters(filter)
    rows = get_client().list_projects(limit=limit, query=query)
    filtered_rows = apply_filters(rows, filter) if filter else rows
    _print_rows(filtered_rows, table=table, properties=properties, columns=LIST_COLUMNS)


@app.command("get")
@command
def get_project(
    project_id_or_key: str = typer.Argument(..., help="Jira project id or key"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a Jira project."""
    row = get_client().get_project(project_id_or_key)
    if table and properties is None:
        print_table(
            [{"field": key, "value": value} for key, value in row.items()],
            ["field", "value"],
            ["Field", "Value"],
        )
        return
    if not table and properties is None:
        print_json(row)
        return
    _print_rows([row], table=table, properties=properties, columns=LIST_COLUMNS)
