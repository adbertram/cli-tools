"""Messenger commands for Facebook CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "requests": [
        "browser_session"
    ],
    "send": [
        "browser_session"
    ]
}

import typer
from typing import Optional, List

from cli_tools_shared.output import print_json, print_table, handle_error

from .._helpers import client_session, output_list

app = typer.Typer(help="Facebook Messenger conversations and messages", no_args_is_help=True)

DEFAULT_COLUMNS = ["id", "name", "snippet"]
DEFAULT_HEADERS = ["ID", "Name", "Snippet"]

MESSAGE_COLUMNS = ["text"]
MESSAGE_HEADERS = ["Text"]


@app.command("list")
def messenger_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of conversations"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List Messenger conversations.

    Examples:
        facebook messenger list
        facebook messenger list --table --limit 10
        facebook messenger list --filter "name:contains:John"
        facebook messenger list --properties id,name
    """
    try:
        with client_session() as client:
            conversations = client.list_conversations(limit=limit)

            output_list(
                conversations, table=table, filter=filter, properties=properties,
                limit=limit, default_columns=DEFAULT_COLUMNS,
                default_headers=DEFAULT_HEADERS, noun="conversation",
            )
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def messenger_get(
    conversation_id: str = typer.Argument(..., help="Conversation/thread ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of messages"),
):
    """Get a conversation with its messages.

    Examples:
        facebook messenger get 123456789
        facebook messenger get 123456789 --table
        facebook messenger get 123456789 --limit 20
    """
    try:
        with client_session() as client:
            result = client.get_conversation(conversation_id, message_limit=limit)

            if table:
                messages = result.get("messages", [])
                if not messages:
                    print("No messages found.")
                    return
                print_table(messages, MESSAGE_COLUMNS, MESSAGE_HEADERS)
            else:
                print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def messenger_send(
    conversation_id: str = typer.Argument(..., help="Conversation/thread ID"),
    text: str = typer.Option(..., "--text", "-m", help="Message text to send"),
):
    """Send a message to a conversation.

    Examples:
        facebook messenger send 123456789 --text "Hello!"
        facebook messenger send 123456789 -m "Thanks for your message"
    """
    try:
        with client_session() as client:
            result = client.send_message(conversation_id, text)
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("requests")
def messenger_requests(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of requests"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List message requests.

    Examples:
        facebook messenger requests
        facebook messenger requests --table
        facebook messenger requests --limit 10
    """
    try:
        with client_session() as client:
            requests_list = client.list_requests(limit=limit)

            output_list(
                requests_list, table=table, filter=filter, properties=properties,
                limit=limit, default_columns=DEFAULT_COLUMNS,
                default_headers=DEFAULT_HEADERS, noun="message request",
            )
    except Exception as e:
        raise typer.Exit(handle_error(e))
