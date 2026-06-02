"""Conversations commands for iMessage CLI."""
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
)
from pydantic import BaseModel

from ..client import get_client

app = typer.Typer(help="Manage conversations", no_args_is_help=True)


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
def conversations_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of conversations to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List recent conversations from iMessage.

    Examples:
        imessage conversations list
        imessage conversations list --table
        imessage conversations list --limit 20
        imessage conversations list --filter "service:iMessage"
        imessage conversations list --properties "id,display_name,last_message_text"
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
        conversations = client.list_conversations(limit=limit)

        # Apply client-side filters
        if filter and isinstance(conversations, list):
            conversations_dict = [model_to_dict(conv) for conv in conversations]
            conversations_dict = apply_filters(conversations_dict, filter)
            conversations = conversations_dict

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            conversations = extract_fields(conversations, fields)

        if table:
            if not conversations:
                print("No conversations found.")
                return

            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table(conversations, columns, columns)
            else:
                # Default columns for Conversation model
                columns = ["id", "display_name", "last_message_text", "service"]
                headers = ["ID", "Name", "Last Message", "Service"]
                print_table(conversations, columns, headers)
        else:
            print_json(conversations)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def conversations_get(
    conversation_id: str = typer.Argument(..., help="The conversation ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get a conversation with its recent messages.

    Examples:
        imessage conversations get CONVERSATION_ID
        imessage conversations get CONVERSATION_ID --table
        imessage conversations get CONVERSATION_ID --properties "id,display_name,message_count"
    """
    try:
        client = get_client()
        conversation = client.get_conversation(conversation_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            conversation = extract_fields([conversation], fields)[0]

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table([conversation], columns, columns)
            else:
                # Convert model to key-value table
                conversation_dict = model_to_dict(conversation)
                rows = [{"field": k, "value": str(v)[:60]} for k, v in conversation_dict.items() if v is not None and k != "messages"]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(conversation)

    except Exception as e:
        raise typer.Exit(handle_error(e))
