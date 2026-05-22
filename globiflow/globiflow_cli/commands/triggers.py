"""Trigger commands for Globiflow CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

import typer
from typing import Optional, List

from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error, print_info, print_error
from cli_tools_shared import FilterMap

app = typer.Typer(help="Manage Globiflow triggers")


def _apply_filters(items: List[dict], filters: Optional[List[str]]) -> List[dict]:
    """Apply client-side filters using field:op:value format.

    Args:
        items: List of dicts to filter
        filters: List of filter strings in format "field:op:value"
                 Supported operators: eq, ne, contains, gt, lt, gte, lte

    Returns:
        Filtered list of dicts
    """
    if not filters:
        return items

    filtered = items
    for filter_str in filters:
        parts = filter_str.split(":", 2)
        if len(parts) != 3:
            print_error(f"Invalid filter format: {filter_str}. Expected field:op:value")
            continue

        field, op, value = parts

        # Apply filter
        if op == "eq":
            filtered = [item for item in filtered if str(item.get(field, "")).lower() == value.lower()]
        elif op == "ne":
            filtered = [item for item in filtered if str(item.get(field, "")).lower() != value.lower()]
        elif op == "contains":
            filtered = [item for item in filtered if value.lower() in str(item.get(field, "")).lower()]
        elif op == "gt":
            filtered = [item for item in filtered if str(item.get(field, "")) > value]
        elif op == "lt":
            filtered = [item for item in filtered if str(item.get(field, "")) < value]
        elif op == "gte":
            filtered = [item for item in filtered if str(item.get(field, "")) >= value]
        elif op == "lte":
            filtered = [item for item in filtered if str(item.get(field, "")) <= value]
        else:
            print_error(f"Unsupported operator: {op}. Use eq, ne, contains, gt, lt, gte, lte")

    return filtered


def _select_properties(items: List[dict], properties: Optional[str]) -> List[dict]:
    """Select specific properties from items.

    Args:
        items: List of dicts
        properties: Comma-separated list of field names to include

    Returns:
        List of dicts with only selected properties
    """
    if not properties:
        return items

    fields = [f.strip() for f in properties.split(",")]
    return [{k: v for k, v in item.items() if k in fields} for item in items]


@app.command("list")
def list_triggers(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results (client-side)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include in output"),
):
    """
    List all available trigger types for flows.

    Shows all trigger types that can be used when creating a new flow.
    Each trigger has a code (used with --trigger flag) and description.
    Supports client-side filtering and limiting (static data).

    Example:
        globiflow triggers list --table
        globiflow triggers list --filter "code:eq:C"
        globiflow triggers list --properties "code,name"
    """
    try:
        client = get_client()
        triggers = client.list_triggers()

        # Convert to dicts for filtering
        trigger_dicts = [t.model_dump() for t in triggers]

        # Apply filters
        trigger_dicts = _apply_filters(trigger_dicts, filter)

        # Apply limit
        trigger_dicts = trigger_dicts[:limit]

        # Select properties if specified
        trigger_dicts = _select_properties(trigger_dicts, properties)

        if table:
            if trigger_dicts:
                # Determine columns based on properties or default
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                    headers = [c.replace("_", " ").title() for c in columns]
                else:
                    columns = ["code", "name", "description"]
                    headers = ["Code", "Name", "Description"]

                print_table(trigger_dicts, columns, headers)
            else:
                print_info("No triggers found.")
        else:
            print_json(trigger_dicts)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_trigger(
    code: str = typer.Argument(..., help="Trigger code (e.g., C, U, M)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific trigger type by code.

    Example:
        globiflow triggers get C --table
        globiflow triggers get M
    """
    try:
        client = get_client()
        triggers = client.list_triggers()

        # Accept either the trigger code or the human-readable name.
        trigger = None
        for t in triggers:
            if t.code.upper() == code.upper() or t.name.lower() == code.lower():
                trigger = t
                break

        if not trigger:
            print_error(f"Trigger with code '{code}' not found")
            raise typer.Exit(1)

        if table:
            rows = [
                {"field": "Code", "value": trigger.code},
                {"field": "Name", "value": trigger.name},
                {"field": "Description", "value": trigger.description},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(trigger)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
