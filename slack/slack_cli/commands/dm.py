"""Direct message commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "read": [
        "custom"
    ],
    "send": [
        "custom"
    ]
}

import re
import typer
from typing import Optional, Dict, List
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage direct messages")

# Cache for user ID to name mapping
_user_cache: Dict[str, Dict] = {}


def _get_user_info(client, user_id: str) -> Dict:
    """Get user info from user ID, with caching."""
    if not user_id:
        return {}

    if user_id in _user_cache:
        return _user_cache[user_id]

    try:
        response = client.get_user_info(user_id)
        user = response.get("user", {})
        _user_cache[user_id] = user
        return user
    except Exception:
        return {}


def _get_user_display_name(client, user_id: str) -> str:
    """Get user display name from user ID."""
    user = _get_user_info(client, user_id)
    if not user:
        return user_id
    # Prefer display_name, fall back to real_name, then name
    return (
        user.get("profile", {}).get("display_name") or
        user.get("real_name") or
        user.get("name") or
        user_id
    )


def _resolve_user(client, user_identifier: str) -> str:
    """
    Resolve a user identifier to a user ID.

    Accepts:
        - User ID (U1234567890)
        - Email address (user@example.com)
        - @username or username

    Returns:
        User ID

    Raises:
        ClientError: If user cannot be resolved
    """
    # Already a user ID - verify it exists
    if user_identifier.startswith("U") and len(user_identifier) > 8:
        try:
            response = client.get_user_info(user_identifier)
            if response.get("user", {}).get("id"):
                return user_identifier
        except Exception:
            pass
        # User ID not found directly, fall through to search by username/name

    # Email address
    if "@" in user_identifier and "." in user_identifier.split("@")[-1]:
        try:
            response = client.lookup_user_by_email(user_identifier)
            return response.get("user", {}).get("id")
        except ClientError:
            raise ClientError(f"User not found with email: {user_identifier}")

    # Username (with or without @) - also handles invalid user IDs as usernames
    username = user_identifier.lstrip("@").lower()

    # Search through users by name, display_name, or id
    response = client.list_users(limit=1000)
    members = response.get("members", [])

    for user in members:
        # Match by username
        if user.get("name", "").lower() == username:
            return user.get("id")
        # Match by display name
        if user.get("profile", {}).get("display_name", "").lower() == username:
            return user.get("id")
        # Match by user ID (case-insensitive for convenience)
        if user.get("id", "").lower() == user_identifier.lower():
            return user.get("id")

    raise ClientError(f"User not found: {user_identifier}")


def _resolve_mentions(client, text: str) -> str:
    """Replace <@USERID> mentions with actual user names."""
    if not text:
        return text

    # Find all user mentions like <@U1234567890>
    mention_pattern = re.compile(r'<@(U[A-Z0-9]+)>')

    def replace_mention(match):
        user_id = match.group(1)
        name = _get_user_display_name(client, user_id)
        return f"@{name}"

    return mention_pattern.sub(replace_mention, text)


def _get_dm_with_unread_count(client, channel_id: str) -> Dict:
    """Get DM channel info including unread count."""
    try:
        response = client.get_channel_info(channel_id)
        return response.get("channel", {})
    except Exception:
        return {}


def _get_group_dm_display_name(client, channel: Dict) -> str:
    """Get a human-readable display name for a group DM.

    Uses the channel name (e.g. 'mpdm-user1--user2--user3...')
    and attempts to resolve member names. Falls back to the raw name.
    """
    # If Slack provides a purpose or topic, prefer that
    purpose = channel.get("purpose", {}).get("value", "")
    if purpose:
        return purpose

    # Try to get member names from the channel name
    # MPIM names look like: mpdm-user1--user2--user3-1
    name = channel.get("name", "")
    if name.startswith("mpdm-"):
        # Strip 'mpdm-' prefix and trailing group number
        stripped = name[5:]
        # Remove trailing '-N' suffix (group creation counter)
        parts = stripped.rsplit("-", 1)
        if parts[-1].isdigit():
            stripped = parts[0]
        # Split on '--' to get individual usernames
        usernames = [u for u in stripped.split("--") if u]
        if usernames:
            return ", ".join(usernames)

    return name


@app.command("list")
def list_dms(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of DMs to list"),
    unread: bool = typer.Option(False, "--unread", "-u", help="Only show DMs with unread messages"),
    include_group: bool = typer.Option(False, "--include-group", "-g", help="Include group DMs (MPIMs)"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., user:eq:U1234567890, is_open:eq:true)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List direct message conversations.

    Example:
        slack dm list --table
        slack dm list --limit 20
        slack dm list --unread --table
        slack dm list --include-group --table
    """
    try:
        # Validate client-side filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        response = client.list_dms(limit=limit)
        channels = response.get("channels", [])

        # Mark 1:1 DMs with type
        for ch in channels:
            ch["dm_type"] = "direct"

        # Include group DMs if requested
        if include_group:
            group_response = client.list_group_dms(limit=limit)
            group_channels = group_response.get("channels", [])
            for ch in group_channels:
                ch["dm_type"] = "group"
            channels.extend(group_channels)

        # If --unread flag is set, fetch unread counts and filter
        if unread:
            enriched_channels = []
            for ch in channels:
                channel_info = _get_dm_with_unread_count(client, ch.get("id"))
                if channel_info:
                    unread_count = channel_info.get("unread_count", 0)
                    if unread_count > 0:
                        ch["unread_count"] = unread_count
                        ch["unread_count_display"] = channel_info.get("unread_count_display", 0)
                        enriched_channels.append(ch)
            channels = enriched_channels

        for ch in channels:
            if ch.get("dm_type") == "group":
                ch["user_name"] = _get_group_dm_display_name(client, ch)
            else:
                user_id = ch.get("user")
                if user_id:
                    ch["user_name"] = _get_user_display_name(client, user_id)

        # Apply client-side filters
        if filter_:
            channels = apply_filters(channels, filter_)

        if properties:
            channels = apply_properties_filter(channels, properties)

        if table:
            table_data = []
            for ch in channels:
                is_group = ch.get("dm_type") == "group"
                user_id = ch.get("user", "")
                user_name = ch.get("user_name", user_id)
                row = {
                    "id": ch.get("id"),
                    "user_id": "(group)" if is_group else user_id,
                    "user": user_name,
                    "is_open": ch.get("is_open", False),
                }
                if include_group:
                    row["type"] = "group" if is_group else "direct"
                if unread:
                    row["unread"] = ch.get("unread_count", 0)
                table_data.append(row)

            columns = ["id", "user_id", "user", "is_open"]
            headers = ["Channel ID", "User ID", "User", "Open"]

            if include_group:
                columns.insert(3, "type")
                headers.insert(3, "Type")

            if unread:
                columns.append("unread")
                headers.append("Unread")

            print_table(table_data, columns, headers)
        else:
            print_json({"dms": channels, "count": len(channels)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def dm_get(
    user: str = typer.Argument(..., help="User ID, email, or @username"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a direct message conversation with a user.

    Example:
        slack dm get U1234567890
        slack dm get user@example.com --table
    """
    try:
        client = get_client()
        user_id = _resolve_user(client, user)
        dm_response = client.open_dm(user_id)
        channel = dm_response.get("channel", {})
        if not channel:
            raise ClientError("Failed to open DM channel")
        channel["user_name"] = _get_user_display_name(client, user_id)
        if table:
            print_table([{
                "id": channel.get("id"),
                "user": channel.get("user_name", user_id),
                "is_open": channel.get("is_open", False),
            }], ["id", "user", "is_open"], ["Channel ID", "User", "Open"])
        else:
            print_json(channel)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def send_dm(
    user: str = typer.Argument(..., help="User ID, email, @username, or channel ID (for group DMs)"),
    text: str = typer.Argument(..., help="Message text"),
    thread_ts: Optional[str] = typer.Option(None, "--thread-ts", help="Thread timestamp for replies"),
):
    """
    Send a direct message to a user or group DM.

    For 1:1 DMs, specify the user:
        - User ID (U1234567890)
        - Email address (user@example.com)
        - Username (@john.doe or john.doe)

    For group DMs, specify the channel ID directly:
        - Channel ID (C01U109E658)
        - Find channel IDs with: slack dm list --include-group --table

    Example:
        slack dm send U1234567890 "Hello!"
        slack dm send user@example.com "Hello via email lookup!"
        slack dm send @john.doe "Hello John!"
        slack dm send C01U109E658 "Hello group!"  # group DM by channel ID
    """
    try:
        client = get_client()

        # Determine if this is a channel ID (group DM) or a user identifier
        is_group = _is_channel_id(user)

        if is_group:
            channel_id = user
        else:
            user_id = _resolve_user(client, user)

            # Open or get DM channel
            dm_response = client.open_dm(user_id)
            channel_id = dm_response.get("channel", {}).get("id")

            if not channel_id:
                raise ClientError("Failed to open DM channel")

        # Send the message
        response = client.send_message(
            channel=channel_id,
            text=text,
            thread_ts=thread_ts,
        )

        if is_group:
            print_success(f"DM sent to group {channel_id}")
            print_json({
                "ts": response.get("ts"),
                "channel": channel_id,
                "type": "group_dm",
            })
        else:
            user_name = _get_user_display_name(client, user_id)
            print_success(f"DM sent to {user_name}")
            print_json({
                "ts": response.get("ts"),
                "channel": channel_id,
                "user": user_id,
                "user_name": user_name,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


def _is_channel_id(value: str) -> bool:
    """Check if a value looks like a Slack channel ID (e.g., C01U109E658, D01ABC, G01XYZ)."""
    return bool(re.match(r'^[CDG][A-Z0-9]{8,}$', value))


@app.command("read")
def read_dm(
    user: str = typer.Argument(..., help="User ID, email, @username, or channel ID (for group DMs)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of messages"),
    oldest: Optional[str] = typer.Option(None, "--oldest", help="Oldest timestamp (inclusive)"),
    latest: Optional[str] = typer.Option(None, "--latest", help="Latest timestamp (exclusive)"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Client-side filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull",
    ),
):
    """
    Read direct message history with a user or group DM.

    For 1:1 DMs, specify the user:
        - User ID (U1234567890)
        - Email address (user@example.com)
        - Username (@john.doe or john.doe)

    For group DMs, specify the channel ID directly:
        - Channel ID (C01U109E658)
        - Find channel IDs with: slack dm list --include-group --table

    Example:
        slack dm read U1234567890 --table
        slack dm read user@example.com --limit 20
        slack dm read @john.doe --table
        slack dm read C01U109E658 --table  # group DM by channel ID
    """
    try:
        # Validate client-side filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()

        # Determine if this is a channel ID (group DM) or a user identifier
        is_group = _is_channel_id(user)

        if is_group:
            channel_id = user
            target_label = channel_id
        else:
            user_id = _resolve_user(client, user)

            # Open or get DM channel
            dm_response = client.open_dm(user_id)
            channel_id = dm_response.get("channel", {}).get("id")

            if not channel_id:
                raise ClientError("Failed to open DM channel")

            target_label = _get_user_display_name(client, user_id)

        # Get message history
        response = client.get_message_history(
            channel=channel_id,
            limit=limit,
            oldest=oldest,
            latest=latest,
        )

        messages = response.get("messages", [])

        # Apply client-side filters
        if filter_:
            messages = apply_filters(messages, filter_)

        # Get the current user's ID for labeling
        auth = client.auth_test()
        current_user_id = auth.get("user_id")

        if table:
            table_data = []
            for msg in messages:
                sender_id = msg.get("user", "")
                if sender_id == current_user_id:
                    sender = "You"
                elif not is_group and sender_id == user_id:
                    sender = target_label
                else:
                    sender = _get_user_display_name(client, sender_id)

                # Resolve mentions in text
                text = _resolve_mentions(client, msg.get("text", ""))
                text_display = text[:60] + ("..." if len(text) > 60 else "")

                table_data.append({
                    "ts": msg.get("ts"),
                    "from": sender,
                    "text": text_display,
                })
            print_table(
                table_data,
                ["ts", "from", "text"],
                ["Timestamp", "From", "Message"],
            )
        else:
            # Enrich messages with user names and resolve mentions
            for msg in messages:
                if "text" in msg:
                    msg["text"] = _resolve_mentions(client, msg["text"])
                sender_id = msg.get("user")
                if sender_id:
                    if sender_id == current_user_id:
                        msg["from"] = "You"
                    else:
                        msg["from"] = _get_user_display_name(client, sender_id)

            result = {
                "messages": messages,
                "count": len(messages),
                "channel": channel_id,
            }
            if is_group:
                result["type"] = "group_dm"
            else:
                result["with_user"] = user_id
                result["with_user_name"] = target_label
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
