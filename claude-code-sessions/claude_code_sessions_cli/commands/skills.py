"""Skill/command invocation commands for Claude Code Sessions CLI."""
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error
from ..parsers import format_local_time

app = typer.Typer(help="Query skill/command invocations", no_args_is_help=True)


@app.command("list")
def list_skills(
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to specific session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List all skill/command invocations for a project.

    Example:
        claude-code-sessions skills list --project ExampleProject
        claude-code-sessions skills list --project ExampleProject --since 1h
        claude-code-sessions skills list --project ExampleProject --filter "name:eq:start-post-pipeline"
        claude-code-sessions skills list --project ExampleProject --session-id abc123
    """
    try:
        client = get_client()
        skills = client.list_skills(project=project, limit=limit, since=since)

        # Convert to dicts for filtering/output
        items = [s.model_dump() for s in skills]

        # Apply session_id filter
        if session_id:
            items = [item for item in items if item.get('session_id') == session_id]

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            # Format timestamps in local timezone
            for item in items:
                item['time'] = format_local_time(item.get('timestamp', ''))
            columns = ["name", "args", "time"]
            headers = ["Skill/Command", "Args", "Time"]
            print_table(items, columns, headers)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_skill(
    skill_id: str = typer.Argument(..., help="Skill invocation ID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific skill/command invocation.

    Example:
        claude-code-sessions skills get <skill-id> --project ExampleProject
    """
    try:
        client = get_client()
        skill = client.get_skill(skill_id, project)

        if table:
            skill_dict = skill.model_dump()
            skill_dict['time'] = format_local_time(skill_dict.get('timestamp', ''))
            columns = ["name", "args", "time", "session_id"]
            headers = ["Skill/Command", "Args", "Time", "Session"]
            print_table([skill_dict], columns, headers)
        else:
            print_json(skill.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))
