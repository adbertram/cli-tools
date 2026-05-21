"""Skill mention commands."""
import typer
from typing import List, Optional

from ..client import get_client
from .common import emit_list, emit_one

app = typer.Typer(help="Query skill mentions in Codex user prompts", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"]}

SKILL_COLUMNS = ["time", "session_id", "name", "source"]
SKILL_HEADERS = ["Time", "Session", "Name", "Source"]


@app.command("list")
def list_skills(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields"),
):
    """List skill mentions captured in user prompt events."""
    items = get_client().list_skills(project, project_path, session_id, since, limit)
    emit_list(items, table, SKILL_COLUMNS, SKILL_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_skill(
    skill_id: str = typer.Argument(..., help="Skill invocation ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a specific skill mention."""
    emit_one(get_client().get_skill(skill_id), table, SKILL_COLUMNS, properties)
