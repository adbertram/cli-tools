"""User management commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "set-status": [
        "custom"
    ],
    "set-photo": [
        "custom"
    ]
}

import typer
from pathlib import Path
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack users")


@app.command("list")
def list_users(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_deleted: bool = typer.Option(
        False, "--include-deleted", help="Include deleted users (hidden by default)"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of users"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:john, is_admin:eq:true)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List users in the workspace.

    Deleted users are hidden by default. Use --include-deleted to show them.

    Example:
        slack users list --table
        slack users list --include-deleted --table
        slack users list --limit 50
        slack users list --filter "is_admin:eq:true"
    """
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        response = client.list_users(limit=limit)
        users = response.get("members", [])

        # Filter out deleted users by default
        if not include_deleted:
            users = [u for u in users if not u.get("deleted", False)]

        # Apply client-side filters
        if filter_:
            users = apply_filters(users, filter_)

        if properties:
            users = apply_properties_filter(users, properties)

        if table:
            table_data = [
                {
                    "id": user.get("id"),
                    "name": user.get("name"),
                    "real_name": user.get("real_name", ""),
                    "is_admin": user.get("is_admin", False),
                    "is_bot": user.get("is_bot", False),
                    "deleted": user.get("deleted", False),
                }
                for user in users
            ]

            columns = ["id", "name", "real_name", "is_admin", "is_bot"]
            headers = ["ID", "Username", "Real Name", "Admin", "Bot"]

            # Only show deleted column when --include-deleted is used
            if include_deleted:
                columns.append("deleted")
                headers.append("Deleted")

            print_table(table_data, columns, headers)
        else:
            print_json({"users": users, "count": len(users)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def user_get(
    user_id: str = typer.Argument(..., help="User ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get information about a specific user.

    Example:
        slack users get U1234567890
        slack users get U1234567890 --table
    """
    try:
        client = get_client()
        response = client.get_user_info(user_id)
        user = response.get("user", {})

        if table:
            profile = user.get("profile", {})
            table_data = [
                {
                    "id": user.get("id"),
                    "name": user.get("name"),
                    "real_name": user.get("real_name"),
                    "email": profile.get("email", ""),
                    "title": profile.get("title", ""),
                    "phone": profile.get("phone", ""),
                    "is_admin": user.get("is_admin", False),
                    "is_bot": user.get("is_bot", False),
                }
            ]
            print_table(
                table_data,
                ["id", "name", "real_name", "email", "title", "is_admin", "is_bot"],
                ["ID", "Username", "Real Name", "Email", "Title", "Admin", "Bot"],
            )
        else:
            print_json(user)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("set-status")
def set_status(
    text: str = typer.Argument(..., help="Status text"),
    emoji: str = typer.Option("", "--emoji", "-e", help="Status emoji (e.g., :coffee:)"),
    expiration: Optional[int] = typer.Option(None, "--expiration", help="Unix timestamp when status expires"),
):
    """
    Set your status.

    Example:
        slack users set-status "In a meeting" --emoji :calendar:
        slack users set-status "Away" --emoji :palm_tree: --expiration 1640000000
    """
    try:
        client = get_client()
        client.set_user_status(
            status_text=text,
            status_emoji=emoji,
            status_expiration=expiration,
        )

        print_success(f"Status updated to: {text} {emoji}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("set-photo")
def set_photo(
    image_path: Path = typer.Argument(..., help="Path to the profile image file"),
):
    """
    Set your profile photo.

    Example:
        slack users set-photo ./avatar.png
    """
    try:
        client = get_client()
        client.set_user_photo(image_path)
        print_success(f"Profile photo updated: {image_path}")

    except Exception as e:
        raise typer.Exit(handle_error(e))
