"""User commands for Asana CLI."""
import typer
from typing import Optional, List
from ..client import get_client
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Asana users")


def extract_field(data, field_path: str):
    """Extract a field value using dot notation (e.g., 'workspace.name')."""
    parts = field_path.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            idx = int(part)
            value = value[idx] if idx < len(value) else None
        else:
            return None
        if value is None:
            return None
    return value


@app.command("list")
def user_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace ID"),
    limit: Optional[int] = typer.Option(100, "--limit", "-l", help="Limit number of results"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output single field (e.g., 'gid', 'name', 'email')"),
):
    """List users in workspace."""
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                typer.echo(f"Filter error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        users = client.list_users(workspace_id=workspace, limit=limit)

        # Apply filters if provided
        if filter_:
            users = apply_filters(users, filter_)

        if properties:
            for user in users:
                value = extract_field(user, properties)
                if value is not None:
                    print(value)
        elif table:
            print_table(
                users,
                ["gid", "name", "email"],
                ["ID", "Name", "Email"]
            )
        else:
            print_json(users)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def user_get(
    user_id: str = typer.Argument("me", help="User ID (default: 'me' for current user)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get user details. Defaults to current user."""
    try:
        client = get_client()
        user = client.get_user(user_id)

        if table:
            data = {
                "gid": user.get("gid"),
                "name": user.get("name"),
                "email": user.get("email"),
            }
            print_table([data], list(data.keys()), ["ID", "Name", "Email"])
        else:
            print_json(user)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
