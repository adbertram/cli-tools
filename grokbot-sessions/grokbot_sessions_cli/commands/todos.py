"""Todo commands for the Grok Bot Sessions CLI.

Grokbot has no todo/plan record of any kind (no transcript entry kind, no card
type, and no API method), so these commands keep the shared shape and return an
explicit empty result rather than inventing todo items.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_info, print_json, print_table

from ..client import ClientError, get_client
from ._render import apply_row_filters, fetch_limit, select_properties

app = typer.Typer(help="Query todo items (not supported by Grokbot)", no_args_is_help=True)

LEAN = [("id", "ID"), ("position", "#"), ("content", "Content"), ("status", "Status")]


@app.command("list")
@command
def list_todos(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:pending)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List todo items (always empty: Grokbot records none).

    Example:
        grokbot-sessions todos list
        grokbot-sessions todos list --table
    """
    try:
        rows, note = get_client().list_todos()
        fetch_limit(limit, filter)
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)
        print_info(note)

        if table:
            print_table(rows, [column for column, _header in LEAN], [header for _column, header in LEAN], max_columns=0)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_todo(
    todo_id: str = typer.Argument(..., help="Todo id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one todo item (never found: Grokbot records none).

    Example:
        grokbot-sessions todos get 5658aa56-122b-4f56-acd9-5102e4f39d1b:0
    """
    try:
        _rows, note = get_client().list_todos()
        raise ClientError(f"Todo not found: {todo_id}. {note}")

    except ClientError as e:
        raise typer.Exit(handle_error(e))
