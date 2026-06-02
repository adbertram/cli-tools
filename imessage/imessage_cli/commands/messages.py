"""Messages commands for iMessage CLI."""
import typer
from typing import Optional, List
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    validate_filters,
)
from cli_tools_shared.output import (
    print_error,
    print_json,
    print_table,
    handle_error,
    print_success,
)
from pydantic import BaseModel

from ..client import get_client

app = typer.Typer(help="Manage messages", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def messages_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of messages to return"),
    contact: Optional[str] = typer.Option(None, "--contact", help="Filter by contact (phone/email)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List recent messages from iMessage.

    Examples:
        imessage messages list
        imessage messages list --table
        imessage messages list --limit 20
        imessage messages list --contact "+15551234567"
        imessage messages list --filter "is_from_me:true"
        imessage messages list --properties "id,text,date"
    """
    try:
        # Validate filters if provided
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        # When client-side filters are present, fetch without limit so
        # filtering doesn't reduce results below the requested count.
        # The limit is applied after filtering instead.
        sql_limit = limit if not filter else 0
        messages = client.list_messages(limit=sql_limit, contact=contact)

        # Apply client-side filters
        if filter and isinstance(messages, list):
            messages_dict = [model_to_dict(msg) for msg in messages]
            messages_dict = apply_filters(messages_dict, filter)
            messages = messages_dict[:limit]

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            messages = extract_fields(messages, fields)

        if table:
            if not messages:
                print("No messages found.")
                return

            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table(messages, columns, columns)
            else:
                # Default columns for Message model
                columns = ["id", "text", "date", "is_from_me", "handle_id"]
                headers = ["ID", "Text", "Date", "From Me", "Handle"]
                print_table(messages, columns, headers)
        else:
            print_json(messages)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def messages_get(
    message_id: str = typer.Argument(..., help="The message ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get a specific message by ID.

    Examples:
        imessage messages get MESSAGE_ID
        imessage messages get MESSAGE_ID --table
        imessage messages get MESSAGE_ID --properties "id,text,date"
    """
    try:
        client = get_client()
        message = client.get_message(message_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            message = extract_fields([message], fields)[0]

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table([message], columns, columns)
            else:
                # Convert model to key-value table
                message_dict = model_to_dict(message)
                rows = [{"field": k, "value": str(v)[:60]} for k, v in message_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(message)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def messages_send(
    recipient: str = typer.Argument(..., help="Recipient phone number or email"),
    text: str = typer.Argument(..., help="Message text to send"),
):
    """
    Send a message via iMessage.

    Recipient can be a phone number or email address.
    Phone numbers are auto-normalized (e.g., +1 prefix added for US numbers).

    Examples:
        imessage messages send "+15551234567" "Hello!"
        imessage messages send "user@example.com" "Hi there"
    """
    try:
        client = get_client()
        result = client.send_message(recipient, text)

        print_json(result)
        if result.success:
            print_success(f"Message sent to {result.recipient}")

    except Exception as e:
        raise typer.Exit(handle_error(e))
