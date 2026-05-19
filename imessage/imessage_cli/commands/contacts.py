"""Contacts commands for iMessage CLI."""
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

app = typer.Typer(help="Manage contacts", no_args_is_help=True)


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
def contacts_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of contacts to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List contacts from macOS Contacts app.

    Examples:
        imessage contacts list
        imessage contacts list --table
        imessage contacts list --limit 10
        imessage contacts list --filter "name:like:%john%"
        imessage contacts list --properties "name,phones"
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
        contacts = client.list_contacts(limit=limit)

        # Apply client-side filters
        if filter and isinstance(contacts, list):
            contacts_dict = [model_to_dict(contact) for contact in contacts]
            contacts_dict = apply_filters(contacts_dict, filter)
            contacts = contacts_dict

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            contacts = extract_fields(contacts, fields)

        if table:
            if not contacts:
                print("No contacts found.")
                return

            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table(contacts, columns, columns)
            else:
                # Default columns for Contact model
                columns = ["id", "name", "phones", "emails"]
                headers = ["ID", "Name", "Phones", "Emails"]
                print_table(contacts, columns, headers)
        else:
            print_json(contacts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def contacts_get(
    contact_id: str = typer.Argument(..., help="The contact ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get a specific contact by ID.

    Examples:
        imessage contacts get CONTACT_ID
        imessage contacts get CONTACT_ID --table
        imessage contacts get CONTACT_ID --properties "name,phones"
    """
    try:
        client = get_client()
        contact = client.get_contact(contact_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            contact = extract_fields([contact], fields)[0]

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table([contact], columns, columns)
            else:
                # Convert model to key-value table
                contact_dict = model_to_dict(contact)
                rows = [{"field": k, "value": str(v)[:60]} for k, v in contact_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(contact)

    except Exception as e:
        raise typer.Exit(handle_error(e))
