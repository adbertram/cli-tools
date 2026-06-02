"""Todo/update-plan commands."""
import typer
from typing import List, Optional

from ..client import get_client
from .common import emit_list, emit_one

app = typer.Typer(help="Query update-plan items from Codex sessions", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"]}

TODO_COLUMNS = ["time", "session_id", "status", "content"]
TODO_HEADERS = ["Time", "Session", "Status", "Content"]


@app.command("list")
def list_todos(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields"),
):
    """List update-plan items captured in Codex transcripts."""
    items = get_client().list_todos(project, project_path, session_id, since, limit)
    emit_list(items, table, TODO_COLUMNS, TODO_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_todo(
    todo_id: str = typer.Argument(..., help="Todo ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a specific update-plan item."""
    emit_one(get_client().get_todo(todo_id), table, TODO_COLUMNS, properties)
