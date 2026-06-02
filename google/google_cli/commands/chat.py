"""Google Chat commands."""
COMMAND_CREDENTIALS = {
    "spaces": ["custom"],
    "messages": ["custom"],
    "send": ["custom"],
}

import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client, retry_with_exponential_backoff
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error, print_info
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.filters import apply_filters as _client_side_filter_reference
from ..filter_translator import translate_chat_filters
from ..parsers import format_local_time

logger = get_activity_logger("google")

CHAT_APP_NOT_CONFIGURED_MSG = (
    "Google Chat API requires a configured Chat app in your Google Cloud project.\n"
    "This is a one-time setup even when using user OAuth credentials.\n\n"
    "To fix:\n"
    "  1. Go to https://console.cloud.google.com/apis/api/chat.googleapis.com/hangouts-chat\n"
    "  2. Fill in App name, Avatar URL, and Description\n"
    "  3. Click Save\n\n"
    "After saving, re-run your command."
)


def _handle_chat_http_error(e: HttpError):
    """Handle Chat API HTTP errors with actionable guidance for common issues."""
    if e.resp.status == 404 and "Chat app not found" in str(e):
        print_error(CHAT_APP_NOT_CONFIGURED_MSG)
    else:
        print_error(f"HTTP error: {e}")
    raise typer.Exit(1)

app = typer.Typer(help="Access Google Chat messages")
spaces_app = typer.Typer(help="Manage Chat spaces")
messages_app = typer.Typer(help="Manage Chat messages")
app.add_typer(spaces_app, name="spaces")
app.add_typer(messages_app, name="messages")


@spaces_app.command("list")
def spaces_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of spaces to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Chat spaces the user belongs to."""
    try:
        client = get_client(profile=profile)
        service = client.get_chat_service()
        logger.info("chat spaces list (limit=%d)", limit)

        list_params = {
            "pageSize": min(limit, 1000),
        }

        # Chat spaces.list filter supports spaceType (SPACE, GROUP_CHAT, DIRECT_MESSAGE)
        if filter:
            # Parse filter for native space type filtering
            filter_parts = []
            for f in filter:
                if f.startswith("spaceType:") or f.startswith("type:"):
                    # Extract value after operator
                    tokens = f.split(":")
                    value = tokens[-1].upper()
                    # Map common aliases
                    type_map = {
                        "ROOM": "SPACE",
                        "DM": "DIRECT_MESSAGE",
                        "GROUP": "GROUP_CHAT",
                    }
                    value = type_map.get(value, value)
                    filter_parts.append(f"spaceType = \"{value}\"")
                else:
                    filter_parts.append(f)
            if filter_parts:
                list_params["filter"] = " OR ".join(filter_parts)

        all_spaces = []
        page_token = None

        while len(all_spaces) < limit:
            if page_token:
                list_params["pageToken"] = page_token

            results = retry_with_exponential_backoff(
                lambda: service.spaces().list(**list_params).execute()
            )
            spaces = results.get("spaces", [])
            all_spaces.extend(spaces)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        all_spaces = all_spaces[:limit]

        if not all_spaces:
            return

        # Default properties
        default_props = ["name", "displayName", "type", "spaceType"]
        props_to_include = properties if properties else default_props

        formatted = []
        for space in all_spaces:
            full_space = {
                "name": space.get("name", ""),
                "displayName": space.get("displayName", ""),
                "type": space.get("type", ""),
                "spaceType": space.get("spaceType", ""),
                "description": (space.get("spaceDetails") or {}).get("description", ""),
                "threaded": space.get("threaded", False),
                "singleUserBotDm": space.get("singleUserBotDm", False),
            }

            if properties:
                full_space = {k: v for k, v in full_space.items() if k in props_to_include}

            formatted.append(full_space)

        if table:
            table_cols = [p for p in ["displayName", "name", "spaceType"] if p in props_to_include or not properties]
            table_headers = {"displayName": "Name", "name": "Space ID", "spaceType": "Type"}
            print_table(formatted, table_cols, [table_headers.get(c, c.title()) for c in table_cols])
        else:
            print_json(formatted)

    except HttpError as e:
        _handle_chat_http_error(e)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@spaces_app.command("get")
def spaces_get(
    space_id: str = typer.Argument(..., help="Space ID (e.g., 'spaces/AAAA' or just 'AAAA')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get details of a specific Chat space."""
    try:
        client = get_client(profile=profile)
        service = client.get_chat_service()
        logger.info("chat spaces get %s", space_id)

        # Normalize space name
        name = space_id if space_id.startswith("spaces/") else f"spaces/{space_id}"

        space = retry_with_exponential_backoff(
            lambda: service.spaces().get(name=name).execute()
        )

        if table:
            data = [{
                "displayName": space.get("displayName", ""),
                "name": space.get("name", ""),
                "spaceType": space.get("spaceType", ""),
            }]
            print_table(data, ["displayName", "name", "spaceType"], ["Name", "Space ID", "Type"])
        else:
            print_json(space)

    except HttpError as e:
        _handle_chat_http_error(e)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@messages_app.command("list")
def messages_list(
    space: str = typer.Option(..., "--space", "-s", help="Space ID (e.g., 'spaces/AAAA' or just 'AAAA')"),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum number of messages to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    order: str = typer.Option("createTime desc", "--order", "-o", help="Order by (default: 'createTime desc')"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List messages in a Chat space."""
    try:
        client = get_client(profile=profile)
        service = client.get_chat_service()
        logger.info("chat messages list (space=%s, limit=%d)", space, limit)

        # Normalize space name
        parent = space if space.startswith("spaces/") else f"spaces/{space}"

        list_params = {
            "parent": parent,
            "pageSize": min(limit, 1000),
            "orderBy": order,
        }

        # Translate CLI filters to Chat API filter string
        if filter:
            filter_str = translate_chat_filters(filter)
            if filter_str:
                list_params["filter"] = filter_str

        all_messages = []
        page_token = None

        while len(all_messages) < limit:
            if page_token:
                list_params["pageToken"] = page_token

            results = retry_with_exponential_backoff(
                lambda: service.spaces().messages().list(**list_params).execute()
            )
            messages = results.get("messages", [])
            all_messages.extend(messages)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        all_messages = all_messages[:limit]

        if not all_messages:
            return

        # Default properties
        default_props = ["name", "sender", "createTime", "text"]
        props_to_include = properties if properties else default_props

        formatted = []
        for msg in all_messages:
            sender = msg.get("sender", {})
            full_msg = {
                "name": msg.get("name", ""),
                "sender": sender.get("displayName", sender.get("name", "")),
                "senderType": sender.get("type", ""),
                "createTime": msg.get("createTime", ""),
                "text": msg.get("text", ""),
                "thread": msg.get("thread", {}).get("name", ""),
                "space": msg.get("space", {}).get("displayName", ""),
            }

            if properties:
                full_msg = {k: v for k, v in full_msg.items() if k in props_to_include}

            formatted.append(full_msg)

        if table:
            # Format timestamps for table display
            for msg in formatted:
                if "createTime" in msg:
                    msg["createTime"] = format_local_time(msg["createTime"])
            table_cols = [p for p in ["sender", "createTime", "text"] if p in props_to_include or not properties]
            table_headers = {"sender": "Sender", "createTime": "Time", "text": "Message"}
            print_table(formatted, table_cols, [table_headers.get(c, c.title()) for c in table_cols])
        else:
            print_json(formatted)

    except HttpError as e:
        _handle_chat_http_error(e)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@messages_app.command("get")
def messages_get(
    message_name: str = typer.Argument(..., help="Message name (e.g., 'spaces/AAAA/messages/BBBB')"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a specific Chat message."""
    try:
        client = get_client(profile=profile)
        service = client.get_chat_service()
        logger.info("chat messages get %s", message_name)

        msg = retry_with_exponential_backoff(
            lambda: service.spaces().messages().get(name=message_name).execute()
        )

        if table:
            sender = msg.get("sender", {})
            data = [{
                "sender": sender.get("displayName", sender.get("name", "")),
                "createTime": format_local_time(msg.get("createTime", "")),
                "text": msg.get("text", ""),
            }]
            print_table(data, ["sender", "createTime", "text"], ["Sender", "Time", "Message"])
        else:
            print_json(msg)

    except HttpError as e:
        _handle_chat_http_error(e)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def chat_send(
    space: str = typer.Option(..., "--space", "-s", help="Space ID (e.g., 'spaces/AAAA' or just 'AAAA')"),
    text: str = typer.Option(..., "--text", "-t", help="Message text to send"),
    confirm: bool = typer.Option(False, "--confirm", help="Actually send the message. Without this flag, only previews."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Send a message to a Chat space.

    By default, shows a preview of the message without sending.
    Use --confirm to actually send the message.
    """
    try:
        client = get_client(profile=profile)
        service = client.get_chat_service()

        # Normalize space name
        parent = space if space.startswith("spaces/") else f"spaces/{space}"

        logger.info("chat send (space=%s, confirm=%s)", space, confirm)

        if not confirm:
            preview = {
                "space": parent,
                "text": text,
                "status": "preview (not sent)",
            }
            print_json(preview)
            print_info("Use --confirm to actually send this message. The --confirm flag must be approved by a human, not AI.")
            return

        result = retry_with_exponential_backoff(
            lambda: service.spaces().messages().create(
                parent=parent,
                body={"text": text},
            ).execute()
        )

        print_success(f"Message sent. Name: {result.get('name', '')}")
        print_json({
            "name": result.get("name", ""),
            "space": parent,
            "text": text,
            "createTime": result.get("createTime", ""),
            "status": "sent",
        })

    except HttpError as e:
        _handle_chat_http_error(e)
    except Exception as e:
        raise typer.Exit(handle_error(e))
