"""Main entry point for Crowdgen (Appen) CLI."""

import typer
from typing import List, Optional

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_info, print_output

from . import __version__
from .client import ClientError, get_client
from .config import get_config

app = create_app(
    name="crowdgen",
    help="CLI interface for CrowdGen by Appen (browser automation, worker side)",
    version=__version__,
)
tasks_app = typer.Typer(
    help="Manage CrowdGen worker projects/tasks (available until shortlisted)",
    no_args_is_help=True,
)

COLUMNS = {
    "id": "Project ID",
    "title": "Title",
    "url": "URL",
    "status": "Status",
}


def _emit(rows, table: bool, properties: Optional[str], columns: dict) -> None:
    """Render list output (a list of dicts) or single-item output (one dict)."""
    if properties:
        keys = [field.strip() for field in properties.split(",") if field.strip()]
        if isinstance(rows, list):
            rows = apply_properties_filter(rows, properties)
        else:
            rows = apply_properties_filter([rows], properties)[0]
        print_output(rows, table=table, columns=keys, headers=keys)
        return
    print_output(rows, table=table, columns=list(columns), headers=list(columns.values()))


@tasks_app.command("list")
@command
def tasks_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tasks"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:available)"
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """List available worker projects from CrowdGen's projects/available feed.

    CrowdGen work appears only after an account is shortlisted for a project;
    until then the dashboard (and this command) is empty: `[]`.
    """
    if filter:
        validate_filters(filter)
    client = get_client()
    try:
        rows = client.list_tasks(limit=limit)
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    _emit(rows, table, properties, COLUMNS)


@tasks_app.command("get")
@command
def tasks_get(
    task_id: str = typer.Argument(..., help="Project/task ID (from 'tasks list' output's id field)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated properties"),
):
    """Get full detail for a single listed project/task."""
    client = get_client()
    try:
        row = client.get_task(task_id)
    finally:
        client.close()
    _emit(row, table, properties, COLUMNS)


@tasks_app.command("apply")
@command
def tasks_apply(
    task_id: str = typer.Argument(..., help="Project/task ID"),
    confirm: bool = typer.Option(False, "--confirm", help="Unused: apply is always refused"),
):
    """Refusal stub — CrowdGen applications are never automated.

    MicroWorker discovers and reports; applying to a CrowdGen project is
    Adam's decision, done manually in the browser.
    """
    raise ClientError(
        f"Refusing to apply to CrowdGen task {task_id!r}: application is never "
        "automated. Adam applies to CrowdGen projects manually in the browser."
    )


app.add_typer(tasks_app, name="tasks")
app.add_typer(create_auth_app(get_config, tool_name="crowdgen"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
