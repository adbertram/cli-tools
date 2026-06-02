"""Tracking commands for USPS CLI."""
import sys
from typing import List, Optional

import typer

from ..client import get_client, ClientError
from cli_tools_shared import FilterMap
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import (
    print_json,
    print_table,
    handle_error,
)

app = typer.Typer(help="USPS package tracking", no_args_is_help=True)

# Configure filter map for tracking
filter_map = FilterMap()
filter_map.add_argument_mapping("status", "status", "eq")
filter_map.add_argument_mapping("status_category", "status_category", "eq")
filter_map.add_argument_mapping("mail_class", "mail_class", "contains")


def _get_nested_value(obj: dict, path: str):
    """Get value from nested dict using dot notation."""
    keys = path.split(".")
    value = obj
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def _filter_dict_properties(data: dict, properties: List[str]) -> dict:
    """Filter a dict to only include specified properties (supports dot notation)."""
    result = {}
    for prop in properties:
        value = _get_nested_value(data, prop)
        if value is not None:
            # Use the full path as key for nested properties
            result[prop] = value
    return result


@app.command("get")
def tracking_get(
    tracking_number: str = typer.Argument(..., help="USPS tracking number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get tracking information for a package.

    Example:
        usps tracking get 9400111899223456789012
        usps tracking get 9400111899223456789012 --table
    """
    try:
        client = get_client()
        tracking = client.get_tracking(tracking_number)

        if table:
            # Flatten for table display
            data = tracking.model_dump()
            flat_data = {
                "tracking_number": data["tracking_number"],
                "status": data["status"],
                "status_category": data.get("status_category", ""),
                "status_summary": data.get("status_summary", ""),
                "mail_class": data.get("mail_class", ""),
                "expected_delivery": data.get("expected_delivery", ""),
            }
            print_table(
                [flat_data],
                list(flat_data.keys()),
                ["Tracking #", "Status", "Category", "Summary", "Mail Class", "Expected"],
            )
        else:
            print_json(tracking)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def tracking_list(
    tracking_numbers: Optional[List[str]] = typer.Argument(
        None, help="Tracking numbers (or use stdin)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., status:eq:Delivered)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include (e.g., tracking_number,status)",
    ),
):
    """
    Get tracking information for multiple packages.

    Tracking numbers can be provided as arguments or via stdin (one per line).
    If no tracking numbers are provided, returns an empty list.

    Example:
        usps tracking list 9400111899223456789012 9400111899223456789013
        echo "9400111899223456789012" | usps tracking list
        usps tracking list --filter "status:eq:Delivered" --table
        usps tracking list --properties "tracking_number,status,expected_delivery"
    """
    try:
        # Collect tracking numbers from arguments or stdin
        numbers = list(tracking_numbers) if tracking_numbers else []

        # Read from stdin if no arguments and stdin has data
        if not numbers and not sys.stdin.isatty():
            for line in sys.stdin:
                line = line.strip()
                if line:
                    numbers.append(line)

        # If no tracking numbers provided, return empty list/table
        if not numbers:
            if table:
                print_table([], ["tracking_number", "status"], ["Tracking #", "Status"])
            else:
                print_json([])
            return

        client = get_client()
        results = client.get_tracking_batch(
            tracking_numbers=numbers, limit=limit, filters=filter
        )

        if not results:
            print_json([])
            return

        # Convert to dicts for filtering/property selection
        results_dicts = [r.model_dump() for r in results]

        # Apply additional client-side filters if provided
        if filter:
            results_dicts = apply_filters(results_dicts, filter)

        # Apply property filtering if specified
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            results_dicts = [
                _filter_dict_properties(d, prop_list) for d in results_dicts
            ]

        if table:
            # Determine columns from first result
            if results_dicts:
                columns = list(results_dicts[0].keys())
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(results_dicts, columns, headers)
            else:
                print_table([], [], [])
        else:
            print_json(results_dicts)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
