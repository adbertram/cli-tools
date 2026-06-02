"""Message commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "mentions": [
        "custom"
    ],
    "search": [
        "custom"
    ],
    "send": [
        "custom"
    ],
    "threads": [
        "custom"
    ]
}

import re
import typer
from typing import Optional, Dict, List
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack messages")

# Cache for user ID to name mapping
_user_cache: Dict[str, str] = {}
# Cache for name to user ID mapping (reverse lookup)
_name_to_id_cache: Dict[str, str] = {}


def _build_name_to_id_cache(client) -> None:
    """Build a cache mapping user names to user IDs."""
    if _name_to_id_cache:
        return  # Already built

    try:
        cursor = None
        while True:
            response = client.list_users(limit=200, cursor=cursor)
            members = response.get("members", [])

            for user in members:
                user_id = user.get("id", "")
                profile = user.get("profile", {})

                # Store multiple name variations for matching
                names_to_store = []

                # Display name (preferred)
                display_name = profile.get("display_name", "").strip()
                if display_name:
                    names_to_store.append(display_name.lower())

                # Real name
                real_name = user.get("real_name", "").strip()
                if real_name:
                    names_to_store.append(real_name.lower())

                # Username
                name = user.get("name", "").strip()
                if name:
                    names_to_store.append(name.lower())

                # Store all variations
                for n in names_to_store:
                    if n and user_id:
                        _name_to_id_cache[n] = user_id

            # Check for pagination
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    except Exception:
        pass  # Silently fail, mentions just won't be resolved


def _resolve_outgoing_mentions(client, text: str) -> str:
    """Convert @Name mentions to <@USERID> format for Slack API."""
    if not text or "@" not in text:
        return text

    # Build the name cache if needed
    _build_name_to_id_cache(client)

    if not _name_to_id_cache:
        return text  # No cache available

    # Strategy: Find @mentions and try to match the longest possible name
    # Start after @ and greedily capture words, then try to match against cache
    result = text

    # Find all potential @mentions - capture position and everything after @
    mention_starts = [i for i, c in enumerate(text) if c == '@']

    # Process in reverse order to preserve positions when replacing
    for start_pos in reversed(mention_starts):
        # Skip if this looks like an email (@ preceded by alphanumeric)
        if start_pos > 0 and text[start_pos - 1].isalnum():
            continue

        # Skip if already a Slack mention format <@...>
        if start_pos > 0 and text[start_pos - 1] == '<':
            continue

        # Extract potential name (everything after @ until punctuation or special char)
        remaining = text[start_pos + 1:]
        match = re.match(r'^([A-Za-z][A-Za-z0-9 ]*)', remaining)
        if not match:
            continue

        potential_name = match.group(1).strip()
        if not potential_name:
            continue

        # Try to find the best match - start with full name and reduce
        words = potential_name.split()
        matched_user_id = None
        matched_length = 0

        # Try progressively shorter combinations
        for num_words in range(len(words), 0, -1):
            test_name = ' '.join(words[:num_words]).lower()

            # Exact match
            if test_name in _name_to_id_cache:
                matched_user_id = _name_to_id_cache[test_name]
                matched_length = len(' '.join(words[:num_words]))
                break

        # If no exact match, try fuzzy matching on the full potential name
        if not matched_user_id:
            test_name = potential_name.lower()
            for cached_name, user_id in _name_to_id_cache.items():
                if test_name == cached_name:
                    matched_user_id = user_id
                    matched_length = len(potential_name)
                    break

        if matched_user_id:
            # Replace the @name with <@USERID>
            end_pos = start_pos + 1 + matched_length
            result = result[:start_pos] + f"<@{matched_user_id}>" + result[end_pos:]

    return result


def _get_user_name(client, user_id: str) -> str:
    """Get user display name from user ID, with caching."""
    if not user_id:
        return "unknown"

    if user_id in _user_cache:
        return _user_cache[user_id]

    try:
        response = client.get_user_info(user_id)
        user = response.get("user", {})
        # Prefer display_name, fall back to real_name, then name
        name = (
            user.get("profile", {}).get("display_name") or
            user.get("real_name") or
            user.get("name") or
            user_id
        )
        _user_cache[user_id] = name
        return name
    except Exception:
        _user_cache[user_id] = user_id
        return user_id


def _resolve_mentions(client, text: str) -> str:
    """Replace <@USERID> mentions with actual user names."""
    if not text:
        return text

    # Find all user mentions like <@U1234567890>
    mention_pattern = re.compile(r'<@(U[A-Z0-9]+)>')

    def replace_mention(match):
        user_id = match.group(1)
        name = _get_user_name(client, user_id)
        return f"@{name}"

    return mention_pattern.sub(replace_mention, text)


@app.command("send")
def send_message(
    channel: str = typer.Argument(..., help="Channel ID or name"),
    text: str = typer.Argument(..., help="Message text"),
    thread_ts: Optional[str] = typer.Option(None, "--thread-ts", help="Thread timestamp for replies"),
    username: Optional[str] = typer.Option(None, "--username", help="Bot username override"),
):
    """
    Send a message to a channel.

    Mentions: Use @Name or @First Last to mention users. The CLI will
    automatically convert these to proper Slack mentions.

    Example:
        slack messages send C1234567890 "Hello, World!"
        slack messages send C1234567890 "Hello @John Smith"
        slack messages send C1234567890 "Reply" --thread-ts 1234567890.123456
    """
    try:
        client = get_client()

        # Resolve @Name mentions to <@USERID> format
        resolved_text = _resolve_outgoing_mentions(client, text)

        response = client.send_message(
            channel=channel,
            text=resolved_text,
            thread_ts=thread_ts,
            username=username,
        )

        print_json({
            "ts": response.get("ts"),
            "channel": response.get("channel"),
        })
        print_success(f"Message sent successfully")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def message_get(
    channel: str = typer.Argument(..., help="Channel ID"),
    ts: str = typer.Argument(..., help="Message timestamp"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific message by channel and timestamp.

    Example:
        slack messages get C1234567890 1234567890.123456
        slack messages get C1234567890 1234567890.123456 --table
    """
    try:
        client = get_client()
        response = client.get_message_history(
            channel=channel, limit=1, oldest=ts, latest=ts, inclusive=True
        )
        messages = response.get("messages", [])
        if not messages:
            typer.echo(f"Message {ts} not found in channel {channel}", err=True)
            raise typer.Exit(1)
        msg = messages[0]
        if table:
            user_id = msg.get("user", "unknown")
            user_name = _get_user_name(client, user_id) if user_id.startswith("U") else user_id
            text = _resolve_mentions(client, msg.get("text", ""))
            print_table([{
                "ts": msg.get("ts"),
                "user": user_name,
                "text": text[:80],
                "type": msg.get("type"),
            }], ["ts", "user", "text", "type"], ["Timestamp", "User", "Text", "Type"])
        else:
            if "text" in msg:
                msg["text"] = _resolve_mentions(client, msg["text"])
            print_json(msg)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def list_messages(
    channel: str = typer.Argument(..., help="Channel ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of messages"),
    oldest: Optional[str] = typer.Option(None, "--oldest", help="Oldest timestamp (inclusive) - API filter"),
    latest: Optional[str] = typer.Option(None, "--latest", help="Latest timestamp (exclusive) - API filter"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., user:eq:U1234567890, type:eq:message)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List messages from a channel.

    API filters (server-side): --oldest, --latest (timestamp-based)
    Client-side filters: --filter for user, text, type, etc.

    Example:
        slack messages list C1234567890 --table
        slack messages list C1234567890 --limit 50
        slack messages list C1234567890 --filter "user:eq:U1234567890"
        slack messages list C1234567890 --filter "type:eq:message"
    """
    try:
        # Validate client-side filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        # API filtering with oldest/latest
        response = client.get_message_history(
            channel=channel,
            limit=limit,
            oldest=oldest,
            latest=latest,
        )

        messages = response.get("messages", [])

        # Apply client-side filters
        if filter_:
            messages = apply_filters(messages, filter_)

        if properties:
            messages = apply_properties_filter(messages, properties)

        if table:
            table_data = []
            for msg in messages:
                # Resolve user ID to name
                user_id = msg.get("user", msg.get("username", "unknown"))
                user_name = _get_user_name(client, user_id) if user_id and user_id.startswith("U") else user_id

                # Resolve mentions in text
                text = _resolve_mentions(client, msg.get("text", ""))
                text_display = text[:50] + ("..." if len(text) > 50 else "")

                table_data.append({
                    "ts": msg.get("ts"),
                    "user": user_name,
                    "text": text_display,
                    "type": msg.get("type"),
                })
            print_table(
                table_data,
                ["ts", "user", "text", "type"],
                ["Timestamp", "User", "Text", "Type"],
            )
        else:
            # Also resolve mentions in JSON output
            for msg in messages:
                if "text" in msg:
                    msg["text"] = _resolve_mentions(client, msg["text"])
                if "user" in msg and msg["user"].startswith("U"):
                    msg["user_name"] = _get_user_name(client, msg["user"])
            print_json({"messages": messages, "count": len(messages)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def search_messages(
    query: str = typer.Argument(..., help="Search query (API filter)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    count: int = typer.Option(20, "--count", "-c", help="Number of results"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Client-side filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull",
    ),
):
    """
    Search messages in the workspace.

    API filter: query argument (Slack search syntax)
    Client-side filters: --filter for additional filtering on results

    Example:
        slack messages search "hello world"
        slack messages search "error" --table
        slack messages search "error" --count 50
        slack messages search "from:@user" --filter "channel.name:eq:general"
    """
    try:
        # Validate client-side filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        response = client.search_messages(query=query, count=count, page=page)
        matches = response.get("messages", {}).get("matches", [])
        total_count = response.get("messages", {}).get("total", 0)

        # Apply client-side filters
        if filter_:
            matches = apply_filters(matches, filter_)

        if table:
            table_data = [
                {
                    "ts": msg.get("ts"),
                    "channel": msg.get("channel", {}).get("name", "unknown"),
                    "user": msg.get("username", "unknown"),
                    "text": msg.get("text", "")[:50] + ("..." if len(msg.get("text", "")) > 50 else ""),
                }
                for msg in matches
            ]
            print_table(
                table_data,
                ["ts", "channel", "user", "text"],
                ["Timestamp", "Channel", "User", "Text"],
            )
        else:
            print_json({
                "matches": matches,
                "total": total_count,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def delete_message(
    channel: str = typer.Argument(..., help="Channel ID"),
    ts: str = typer.Argument(..., help="Message timestamp"),
):
    """
    Delete a message.

    Example:
        slack messages delete C1234567890 1234567890.123456
    """
    try:
        client = get_client()
        client.delete_message(channel=channel, ts=ts)
        print_success(f"Message {ts} deleted from channel {channel}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("mentions")
def list_mentions(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    count: int = typer.Option(20, "--count", "-c", help="Number of results"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Client-side filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull",
    ),
):
    """
    List messages that mention you.

    Searches for messages where you are mentioned (@you) across all channels.

    Example:
        slack messages mentions --table
        slack messages mentions --count 50
    """
    try:
        # Validate client-side filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        current_user_id = client.get_current_user_id()
        response = client.search_messages(query=f"<@{current_user_id}>", count=count, page=1)
        matches = response.get("messages", {}).get("matches", [])
        total_count = response.get("messages", {}).get("total", 0)

        # Apply client-side filters
        if filter_:
            matches = apply_filters(matches, filter_)

        if table:
            table_data = []
            for msg in matches:
                text = msg.get("text", "")[:50] + ("..." if len(msg.get("text", "")) > 50 else "")
                table_data.append({
                    "ts": msg.get("ts"),
                    "channel": msg.get("channel", {}).get("name", "unknown"),
                    "user": msg.get("username", "unknown"),
                    "text": text,
                })
            print_table(
                table_data,
                ["ts", "channel", "user", "text"],
                ["Timestamp", "Channel", "From", "Text"],
            )
        else:
            print_json({
                "mentions": matches,
                "total": total_count,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("threads")
def list_thread_replies(
    channel: str = typer.Argument(..., help="Channel ID containing the thread"),
    thread_ts: str = typer.Argument(..., help="Timestamp of the parent message (thread root)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of replies"),
    oldest: Optional[str] = typer.Option(None, "--oldest", help="Oldest timestamp (inclusive) - API filter"),
    latest: Optional[str] = typer.Option(None, "--latest", help="Latest timestamp (exclusive) - API filter"),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Client-side filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull",
    ),
):
    """
    List replies in a thread.

    API filters (server-side): --oldest, --latest (timestamp-based)
    Client-side filters: --filter for user, text, type, etc.

    Example:
        slack messages threads C1234567890 1234567890.123456 --table
        slack messages threads C1234567890 1234567890.123456 --limit 50
        slack messages threads C1234567890 1234567890.123456 --filter "user:eq:U1234567890"
    """
    try:
        # Validate client-side filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))

        client = get_client()
        response = client.get_thread_replies(
            channel=channel,
            thread_ts=thread_ts,
            limit=limit,
            oldest=oldest,
            latest=latest,
        )

        messages = response.get("messages", [])

        # Apply client-side filters
        if filter_:
            messages = apply_filters(messages, filter_)

        if table:
            table_data = []
            for msg in messages:
                # Resolve user ID to name
                user_id = msg.get("user", msg.get("username", "unknown"))
                user_name = _get_user_name(client, user_id) if user_id and user_id.startswith("U") else user_id

                # Resolve mentions in text
                text = _resolve_mentions(client, msg.get("text", ""))
                text_display = text[:50] + ("..." if len(text) > 50 else "")

                # Check if this is the parent message
                is_parent = msg.get("ts") == msg.get("thread_ts", thread_ts)

                table_data.append({
                    "ts": msg.get("ts"),
                    "user": user_name,
                    "text": text_display,
                    "type": "parent" if is_parent else "reply",
                })
            print_table(
                table_data,
                ["ts", "user", "text", "type"],
                ["Timestamp", "User", "Text", "Type"],
            )
        else:
            # Also resolve mentions in JSON output
            for msg in messages:
                if "text" in msg:
                    msg["text"] = _resolve_mentions(client, msg["text"])
                if "user" in msg and msg["user"].startswith("U"):
                    msg["user_name"] = _get_user_name(client, msg["user"])
            print_json({"messages": messages, "count": len(messages), "thread_ts": thread_ts})

    except Exception as e:
        raise typer.Exit(handle_error(e))
