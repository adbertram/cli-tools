"""Users commands for Notion CLI - list and inspect workspace users.

User IDs from these commands are what `notion comments create --mention`
resolves to. `GET /v1/users` requires the integration's "read user information"
capability; `person.email` is populated only when the "email" capability is also
enabled.
"""
import typer
from typing import Dict, List, Optional

from ..client import get_client
from ..output import command, print_json, print_table
from cli_tools_shared.filters import (
    apply_filters,
    apply_properties_filter,
)

app = typer.Typer(help="List and inspect workspace users")

USER_COLUMNS = ["id", "name", "type", "email"]
USER_HEADERS = ["ID", "Name", "Type", "Email"]


def format_user_for_display(user: Dict) -> Dict:
    """
    Format a raw Notion user object for display.

    The raw ``person`` / ``bot`` sub-objects are preserved so a dot-notation
    filter such as ``person.email:eq:someone@example.com`` resolves against the
    same shape the API returned. ``email`` is a flat convenience field carrying
    ``person.email``.

    Args:
        user: Raw Notion user object

    Returns:
        Simplified record for display
    """
    person = user.get("person") or {}

    record = {
        "id": user.get("id", ""),
        "name": user.get("name", ""),
        "type": user.get("type", ""),
        "email": person.get("email", ""),
        "avatar_url": user.get("avatar_url") or "",
    }

    if "person" in user:
        record["person"] = user["person"]
    if "bot" in user:
        record["bot"] = user["bot"]

    return record


@app.command("list")
@command
def users_list(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of users to return (default: all users)",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help=(
            "Filter: field:op:value "
            "(e.g., type:eq:person, person.email:eq:user@example.com, "
            "name:contains:Mowers)"
        ),
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output (e.g., id,name,email)",
    ),
):
    """
    List every user in the workspace.

    Pagination: Full cursor walk over GET /v1/users (no first-page truncation)
    Filtering: Client-side (Notion has no server-side user name/email filter)

    Examples:

        notion users list --table

        notion users list --filter "type:eq:person" --table

        notion users list --filter "person.email:eq:someone@example.com"

        notion users list --properties "id,name,email" --limit 10
    """
    client = get_client()

    # Filtering is client-side, so the API fetch must not be pre-capped when a
    # filter is present: a matching user could live past the cap.
    api_limit = None if filter else limit

    users = client.list_users_all(limit=api_limit)
    formatted = [format_user_for_display(u) for u in users]

    if filter:
        formatted = apply_filters(formatted, filter)

    if limit is not None:
        formatted = formatted[:limit]

    if properties:
        formatted = apply_properties_filter(formatted, properties)
        cols = [p.strip() for p in properties.split(",") if p.strip()]
        if table:
            print_table(formatted, cols, cols)
            return
        print_json(formatted)
        return

    if table:
        print_table(formatted, USER_COLUMNS, USER_HEADERS)
    else:
        print_json(formatted)


@app.command("get")
@command
def user_get(
    user_id: str = typer.Argument(
        ...,
        help="User ID to retrieve",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as formatted table",
    ),
):
    """
    Get a specific workspace user by ID.

    Examples:

        notion users get fe60dca0-d16a-42d0-a41d-c3491dc972e6 --table
    """
    client = get_client()
    user = client.get_user(user_id)

    formatted = format_user_for_display(user)

    if table:
        print_table([formatted], USER_COLUMNS, USER_HEADERS)
    else:
        print_json(formatted)


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
