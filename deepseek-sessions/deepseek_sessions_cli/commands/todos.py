"""Todo commands for the DeepSeek Sessions CLI.

dsh rewrites the whole list on each `todo/write`, so these commands report the
final list per session.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ._render import add_time, fetch_limit, render_table, select_properties, to_items
from .session_arg import resolve_session_arg

app = typer.Typer(help="Query todo items from sessions", no_args_is_help=True)


@app.command("list")
@command
def list_todos(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:pending)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List the final todo list of each session in a project.

    Example:
        deepseek-sessions todos list --project BricklinkBook --table
        deepseek-sessions todos list -p BricklinkBook --filter "status:eq:in_progress"
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        todos = client.list_todos(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(todos)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "written_at", "written")
            render_table(
                items,
                [("position", "#"), ("content", "Content"), ("status", "Status"),
                 ("session_id", "Session")],
                [("written", "Written"), ("id", "ID")],
                wide,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_todo(
    todo_id: str = typer.Argument(..., help="Todo ID in the form <session id>:<position>"),
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific todo by ID.

    Example:
        deepseek-sessions todos get session-a084bd95-95f4-489f-9ac2-92d9546eb8f4:0 -p BricklinkBook
    """
    try:
        todo = get_client().get_todo(project=project, todo_id=todo_id)

        if not todo:
            print_json({"error": f"Todo '{todo_id}' not found in project '{project}'"})
            raise typer.Exit(1)

        if table:
            print_table([todo.model_dump()], columns=None, headers=None)
        else:
            print_json(todo.model_dump())

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
