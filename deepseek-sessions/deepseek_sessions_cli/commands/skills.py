"""Skill and slash-command commands for the DeepSeek Sessions CLI."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ..parsers import format_local_time
from ._render import add_time, fetch_limit, render_table, select_properties, to_items
from .session_arg import resolve_session_arg

app = typer.Typer(help="Query skill loads and slash commands", no_args_is_help=True)


@app.command("list")
@command
def list_skills(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., kind:eq:skill, name:eq:caveman)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List skill loads (`skill` tool calls) and slash commands in a project.

    Example:
        deepseek-sessions skills list --project LegoScout --table
        deepseek-sessions skills list -p LegoScout --filter "kind:eq:command"
        deepseek-sessions skills list -p CourseCraft --filter "name:eq:caveman"
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        skills = client.list_skills(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(skills)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "timestamp", "time")
            render_table(
                items,
                [("time", "Time"), ("kind", "Kind"), ("name", "Name"),
                 ("args", "Args"), ("session_id", "Session")],
                [("status", "Status"), ("result", "Result"), ("turn", "Turn")],
                wide,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_skill(
    skill_id: str = typer.Argument(..., help="Skill tool call ID or command ID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific skill load or slash command.

    Example:
        deepseek-sessions skills get cmd-a9d512b7-1 --project BricklinkBook
    """
    try:
        skill = get_client().get_skill(skill_id, project)

        if table:
            rows = [
                {"field": "ID", "value": skill.id},
                {"field": "Kind", "value": skill.kind},
                {"field": "Name", "value": skill.name},
                {"field": "Args", "value": skill.args or "N/A"},
                {"field": "Status", "value": skill.status or "N/A"},
                {"field": "Result", "value": skill.result or "N/A"},
                {"field": "Time", "value": format_local_time(skill.timestamp)},
                {"field": "Session", "value": skill.session_id},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(skill.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))
