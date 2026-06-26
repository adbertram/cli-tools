"""Todo commands for Claude Code Sessions CLI."""
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_json, print_table, handle_error

app = typer.Typer(help="Query todo items from sessions", no_args_is_help=True)


@app.command("list")
@command
def list_todos(
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to specific session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List all todos from sessions in a project.

    Example:
        claude-code-sessions todos list --project ExampleProject
        claude-code-sessions todos list --project ExampleProject --filter "status:eq:pending"
        claude-code-sessions todos list --project ExampleProject --since 1d
        claude-code-sessions todos list --project ExampleProject --session-id abc123
    """
    try:
        client = get_client()
        todos = client.list_todos(project=project, limit=limit, since=since)

        # Convert to dicts for filtering/output
        items = [t.model_dump() for t in todos]

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
            columns = ["content", "status", "priority", "session_id"]
            headers = ["Content", "Status", "Priority", "Session"]
            print_table(items, columns, headers)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_todo(
    todo_id: str = typer.Argument(..., help="Todo ID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific todo by ID.

    Example:
        claude-code-sessions todos get <todo-id> --project ExampleProject
    """
    try:
        client = get_client()
        todo = client.get_todo(project=project, todo_id=todo_id)

        if not todo:
            print_json({"error": f"Todo with ID '{todo_id}' not found in project '{project}'"})
            raise typer.Exit(1)

        item = todo.model_dump()

        if table:
            print_table([item], columns=None, headers=None)
        else:
            print_json(item)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
