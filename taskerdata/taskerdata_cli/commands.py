"""Task commands for TaskerData CLI."""
COMMAND_CREDENTIALS = {
    "get": ["browser_session"],
    "list": ["browser_session"],
    "apply": ["browser_session"],
}

from pathlib import Path
from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_info, print_output

from .client import get_client

app = typer.Typer(help="Manage TaskerData worker tasks", no_args_is_help=True)

COLUMNS = {
    "id": "ID",
    "title": "Title",
    "category": "Category",
    "payout": "Payout",
    "status": "Status",
}
APPLY_COLUMNS = {
    "task_id": "Task ID",
    "confirm": "Confirm",
    "submitted": "Submitted",
}


def _emit_rows(rows, *, table, properties, columns):
    """Render rows to JSON or table. `columns` is an ordered {key: header} dict
    (Python 3.7+ dict insertion order is part of the language spec)."""
    dicts = [r.model_dump(mode="json") if isinstance(r, BaseModel) else r for r in rows]
    if properties:
        keys = [p.strip() for p in properties.split(",") if p.strip()]
        print_output(apply_properties_filter(dicts, properties), table=table, columns=keys, headers=keys)
        return
    print_output(dicts, table=table, columns=list(columns), headers=list(columns.values()))


@app.command("list")
@command
def tasks_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tasks"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., category:eq:surveys)"
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """List open/available tasks for the logged-in worker."""
    if filter:
        validate_filters(filter)
    rows = get_client().list_tasks(limit=limit)
    if filter:
        rows = apply_filters(rows, filter)
    _emit_rows(rows, table=table, properties=properties, columns=COLUMNS)


@app.command("get")
@command
def tasks_get(
    task_id: str = typer.Argument(..., help="Task ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """Get full detail for a specific task."""
    _emit_rows([get_client().get_task(task_id)], table=table, properties=properties, columns=COLUMNS)


@app.command("apply")
@command
def tasks_apply(
    task_id: str = typer.Argument(..., help="Task ID to apply for / pick up"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually submit the application (default is dry-run)"),
    debug_dir: Optional[str] = typer.Option(None, "--debug-dir", help="Directory for failure artifacts (confirm mode)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as a table"),
):
    """Apply to / pick up a TaskerData task. Default is dry-run (no submission)."""
    client = get_client()
    result = client.apply_task(task_id, confirm=confirm)
    if not confirm:
        print_info(f"DRY RUN: would apply for task {task_id}. Pass --confirm to actually submit.")
    if debug_dir:
        Path(debug_dir).expanduser().mkdir(parents=True, exist_ok=True)
    _emit_rows([result], table=table, properties=None, columns=APPLY_COLUMNS)
