"""Channel management commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "archive": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "join": [
        "custom"
    ],
    "leave": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "members": [
        "custom"
    ]
}

import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_warning, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack channels")


def _get_channel_unread_count(client, channel_id: str) -> dict:
    """Get channel info including unread count."""
    try:
        response = client.get_channel_info(channel_id)
        return response.get("channel", {})
    except Exception:
        return {}


@app.command("list")
def list_channels(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of channels"),
    types: str = typer.Option(
        "public_channel,private_channel",
        "--types",
        help="Channel types (public_channel, private_channel, mpim, im)",
    ),
    include_archived: bool = typer.Option(False, "--include-archived", help="Include archived channels"),
    unread: bool = typer.Option(False, "--unread", "-u", help="Only show channels with unread messages"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:general, is_private:eq:true)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List channels in the workspace.

    Example:
        slack channels list --table
        slack channels list --types public_channel --limit 50
        slack channels list --filter "is_private:eq:true"
        slack channels list --filter "name:ilike:%general%"
        slack channels list --unread --table
    """
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        response = client.list_channels(
            limit=limit,
            types=types,
            exclude_archived=not include_archived,
        )
        channels = response.get("channels", [])

        # If --unread flag is set, fetch unread counts and filter
        if unread:
            enriched_channels = []
            for ch in channels:
                channel_info = _get_channel_unread_count(client, ch.get("id"))
                if channel_info:
                    unread_count = channel_info.get("unread_count", 0)
                    if unread_count > 0:
                        ch["unread_count"] = unread_count
                        ch["unread_count_display"] = channel_info.get("unread_count_display", 0)
                        enriched_channels.append(ch)
            channels = enriched_channels

        # Apply client-side filters
        if filter_:
            channels = apply_filters(channels, filter_)

        if properties:
            channels = apply_properties_filter(channels, properties)

        if table:
            table_data = []
            for ch in channels:
                row = {
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "is_private": ch.get("is_private", False),
                    "is_archived": ch.get("is_archived", False),
                    "num_members": ch.get("num_members", 0),
                }
                if unread:
                    row["unread"] = ch.get("unread_count", 0)
                table_data.append(row)

            columns = ["id", "name", "is_private", "is_archived", "num_members"]
            headers = ["ID", "Name", "Private", "Archived", "Members"]

            if unread:
                columns.append("unread")
                headers.append("Unread")

            print_table(table_data, columns, headers)
        else:
            print_json({"channels": channels, "count": len(channels)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def channel_get(
    channel_id: str = typer.Argument(..., help="Channel ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get information about a specific channel.

    Example:
        slack channels get C1234567890
        slack channels get C1234567890 --table
    """
    try:
        client = get_client()
        response = client.get_channel_info(channel_id)
        channel = response.get("channel", {})

        if table:
            table_data = [
                {
                    "id": channel.get("id"),
                    "name": channel.get("name"),
                    "created": channel.get("created"),
                    "is_private": channel.get("is_private"),
                    "is_archived": channel.get("is_archived"),
                    "num_members": channel.get("num_members"),
                    "topic": channel.get("topic", {}).get("value", ""),
                    "purpose": channel.get("purpose", {}).get("value", ""),
                }
            ]
            print_table(
                table_data,
                ["id", "name", "is_private", "is_archived", "num_members", "topic", "purpose"],
                ["ID", "Name", "Private", "Archived", "Members", "Topic", "Purpose"],
            )
        else:
            print_json(channel)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def create_channel(
    name: str = typer.Argument(..., help="Channel name"),
    private: bool = typer.Option(False, "--private", help="Create a private channel"),
):
    """
    Create a new channel.

    Example:
        slack channels create my-new-channel
        slack channels create my-private-channel --private
    """
    try:
        client = get_client()
        response = client.create_channel(name, is_private=private)
        channel = response.get("channel", {})

        print_success(f"Channel '{channel.get('name')}' created with ID: {channel.get('id')}")
        print_json(channel)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("archive")
def archive_channel(
    channel_id: str = typer.Argument(..., help="Channel ID to archive"),
):
    """
    Archive a channel.

    Example:
        slack channels archive C1234567890
    """
    try:
        client = get_client()
        client.archive_channel(channel_id)
        print_success(f"Channel {channel_id} archived successfully")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("join")
def join_channel(
    channel_id: str = typer.Argument(..., help="Channel ID to join"),
):
    """
    Join a channel.

    Example:
        slack channels join C1234567890
    """
    try:
        client = get_client()
        response = client.join_channel(channel_id)
        channel = response.get("channel", {})

        print_success(f"Joined channel '{channel.get('name')}'")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("leave")
def leave_channel(
    channel_id: str = typer.Argument(..., help="Channel ID to leave"),
):
    """
    Leave a channel.

    Example:
        slack channels leave C1234567890
    """
    try:
        client = get_client()
        client.leave_channel(channel_id)
        print_success(f"Left channel {channel_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("members")
def list_members(
    channel_id: str = typer.Argument(..., help="Channel ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of members"),
    resolve: bool = typer.Option(False, "--resolve", "-r", help="Resolve user IDs to user info"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value). Only applies when --resolve is used.",
    ),
):
    """
    List members of a channel.

    Returns a list of user IDs by default. Use --resolve to get full user info.

    Example:
        slack channels members C1234567890
        slack channels members C1234567890 --table
        slack channels members C1234567890 --resolve --table
        slack channels members C1234567890 --resolve --filter "is_bot:eq:false"
    """
    try:
        # Validate filters first (only applicable with --resolve)
        if filter_ and not resolve:
            print_warning("--filter is only applicable when --resolve is used. Ignoring filters.")
            filter_ = None

        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        response = client.get_channel_members(channel_id, limit=limit)
        member_ids = response.get("members", [])

        if resolve:
            # Resolve user IDs to full user info
            members = []
            for user_id in member_ids:
                try:
                    user_response = client.get_user_info(user_id)
                    user = user_response.get("user", {})
                    members.append(user)
                except Exception as e:
                    # If we can't resolve a user, include their ID with an error note
                    members.append({
                        "id": user_id,
                        "name": None,
                        "real_name": None,
                        "_error": str(e),
                    })

            # Apply client-side filters
            if filter_:
                members = apply_filters(members, filter_)

            if table:
                table_data = [
                    {
                        "id": user.get("id"),
                        "name": user.get("name", ""),
                        "real_name": user.get("real_name", ""),
                        "is_admin": user.get("is_admin", False),
                        "is_bot": user.get("is_bot", False),
                    }
                    for user in members
                ]
                print_table(
                    table_data,
                    ["id", "name", "real_name", "is_admin", "is_bot"],
                    ["ID", "Username", "Real Name", "Admin", "Bot"],
                )
            else:
                print_json({"members": members, "count": len(members)})
        else:
            # Just return the user IDs
            if table:
                table_data = [{"user_id": uid} for uid in member_ids]
                print_table(table_data, ["user_id"], ["User ID"])
            else:
                print_json({"members": member_ids, "count": len(member_ids)})

    except Exception as e:
        raise typer.Exit(handle_error(e))
