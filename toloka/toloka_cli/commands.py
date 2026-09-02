"""Task commands for Toloka CLI."""
COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "apply": ["browser_session"],
}

from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_info, print_output

from .client import get_client

app = typer.Typer(help="Browse and apply to Toloka tasks", no_args_is_help=True)

COLUMNS = {
    "id": "ID",
    "title": "Title",
    "payout": "Payout",
    "status": "Status",
}


def _emit_rows(rows, *, table, properties, columns):
    """Render rows to JSON or table. `columns` is an ordered {key: header} dict
    (Python 3.7+ dict insertion order is part of the language spec)."""
    dicts = list(rows)
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
        None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:open)"
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
    task_id: str = typer.Argument(..., help="Task ID to apply to"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually submit the application (default: dry-run)"),
    debug_dir: Optional[str] = typer.Option(
        None, "--debug-dir", help="Directory for failure artifacts (confirm mode)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as a table"),
):
    """Apply to a task. DRY-RUN by default -- pass --confirm to actually submit."""
    result = get_client().apply_task(
        task_id,
        confirm=confirm,
        log=print_info,
        debug_dir=Path(debug_dir).expanduser() if debug_dir else None,
    )
    result_columns = {key: key.replace("_", " ").title() for key in result}
    _emit_rows([result], table=table, properties=None, columns=result_columns)
