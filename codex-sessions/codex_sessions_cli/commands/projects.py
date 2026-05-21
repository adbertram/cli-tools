"""Project commands."""
import typer
from typing import List, Optional

from ..client import get_client
from .common import emit_list, emit_one

app = typer.Typer(help="List and query Codex projects", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"]}

PROJECT_COLUMNS = ["name", "full_path", "session_count", "last_activity"]
PROJECT_HEADERS = ["Name", "Path", "Sessions", "Last Activity"]


@app.command("list")
def list_projects(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List projects with Codex session transcripts."""
    emit_list(get_client().list_projects(limit=limit), table, PROJECT_COLUMNS, PROJECT_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_project(
    name: str = typer.Argument(..., help="Project name or full path"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a project by name or full path."""
    emit_one(get_client().get_project(name), table, PROJECT_COLUMNS, properties)
