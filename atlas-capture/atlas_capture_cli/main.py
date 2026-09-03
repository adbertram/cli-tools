"""Main entry point for the atlas-capture CLI.

Discovery only. This CLI lists and reads Atlas Capture worker tasks; it never
applies to, accepts, or submits a task — MicroWorker's hard rule (see the
microworker skill): applying is Adam's decision, made in the conversation that
approves the exact task. ``tasks apply`` is a refusal stub that documents that.
"""

import typer
from typing import List, Optional

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import ClientError, get_client
from .config import get_config

app = create_app(
    name="atlas-capture",
    help="Atlas Capture worker portal (audit.atlascapture.io) - discovery only",
    version=__version__,
)

tasks_app = typer.Typer(help="Atlas Capture worker tasks (discovery only)", no_args_is_help=True)
account_app = typer.Typer(help="Atlas Capture account state", no_args_is_help=True)

COLUMNS = ["id", "title", "url", "status"]


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _render(rows, table: bool, properties: Optional[str],
            columns: List[str], empty: str) -> None:
    """Render list output (a list of dicts) or single-item output (one dict)."""
    fields = _property_fields(properties)
    if fields:
        if isinstance(rows, list):
            rows = apply_properties_filter(rows, properties)
        else:
            rows = apply_properties_filter([rows], properties)[0]
        columns = fields
    if not table:
        print_json(rows)
        return
    if isinstance(rows, list) and not rows:
        print_info(empty)
        return
    if isinstance(rows, dict):
        # One record as a Field/Value table for --table without --properties.
        if fields:
            print_table([rows], columns, columns)
        else:
            row_items = [{"field": key, "value": str(value)}
                         for key, value in rows.items()]
            print_table(row_items, ["field", "value"], ["Field", "Value"])
        return
    headers = [column.replace("_", " ").title() for column in columns]
    print_table(rows, columns, headers)


@tasks_app.command("list")
@command
def tasks_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tasks"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:open)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """List tasks Atlas Capture exposes to this account.

    Returns a JSON array on stdout ([] when the account currently has no task
    surface — the /tasks route redirects to /dashboard for this account).
    """
    if filter:
        validate_filters(filter)
    client = get_client()
    try:
        rows = client.list_tasks(limit=limit)
        if filter:
            rows = apply_filters(rows, filter)
        rows = rows[:limit]
    finally:
        client.close()
    _render(rows, table, properties, COLUMNS, "No tasks available.")


@tasks_app.command("get")
@command
def tasks_get(
    task_id: str = typer.Argument(..., help="Task ID (from 'tasks list' output)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get full detail for a single task."""
    client = get_client()
    try:
        row = client.get_task(task_id)
    finally:
        client.close()
    _render(row, table, properties, COLUMNS, "No task found.")


@tasks_app.command("apply")
@command
def tasks_apply(
    task_id: str = typer.Argument(..., help="Task ID (ignored: apply is disabled)"),
    confirm: bool = typer.Option(
        False, "--confirm", "-y", help="Confirmation flag (apply never runs)"
    ),
):
    """Refuse to apply to a task. Discovery never applies.

    MicroWorker hard rule: applying is Adam's decision, made only after he
    approves that exact task in the current conversation. This stub always
    refuses, with or without --confirm.
    """
    print_error(
        "atlas-capture does not apply to tasks: MicroWorker discovery never "
        f"applies. Refusing to apply to task {task_id!r} (--confirm "
        f"given: {confirm}). Adam must approve that exact task in-conversation "
        "before any apply path may run."
    )
    raise typer.Exit(1)


@account_app.command("show")
@command
def account_show(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Show live account facts from the authenticated session (user.me)."""
    client = get_client()
    try:
        row = client.account()
    finally:
        client.close()
    _render(row, table, properties, list(row), "No account record.")


app.add_typer(tasks_app, name="tasks")
app.add_typer(account_app, name="account")
app.add_typer(create_auth_app(get_config, tool_name="atlas-capture"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    try:
        run_app(app, error_types=ClientError)
    except typer.Exit:
        raise


if __name__ == "__main__":
    main()
