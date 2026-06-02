"""Output formatting helpers.

Re-exports standard output functions from cli_tools_shared.output.
CLI-specific helpers defined below.

Stream Usage:
    stdout (fd 1) -> Data only (JSON, tables) - via print_json(), print_table()
    stderr (fd 2) -> Messages only - via print_error(), print_warning(), print_success(), print_info()
"""

from typing import Any, Dict

from cli_tools_shared.output import (  # noqa: F401
    console,
    _format_cell_value,
    _serialize_for_json,
    print_json,
    print_table,
    print_output,
    print_error,
    print_warning,
    print_success,
    print_info,
    handle_error,
)
import json
import re


# --- CLI-specific helpers ---


def _flatten_item(item: Dict) -> Dict:
    """
    Flatten a data item by extracting useful nested values.

    Specifically handles Podio API patterns like config.name.

    Args:
        item: Dictionary to flatten

    Returns:
        Flattened dictionary with nested values promoted
    """
    flat = dict(item)

    # Extract common nested config values
    if 'config' in flat and isinstance(flat['config'], dict):
        config = flat['config']
        # Promote name to top level if not already present
        if 'name' not in flat and 'name' in config:
            flat['name'] = config['name']
        if 'item_name' not in flat and 'item_name' in config:
            flat['item_name'] = config['item_name']
        if 'description' not in flat and 'description' in config:
            flat['description'] = config['description']
        if 'type' not in flat and 'type' in config:
            flat['type'] = config['type']
        # Remove config from output since we extracted what we need
        del flat['config']

    # Extract space_id from push channel (for space objects)
    if 'space_id' not in flat and 'push' in flat and isinstance(flat['push'], dict):
        channel = flat['push'].get('channel', '')
        if channel.startswith('/space/'):
            try:
                flat['space_id'] = int(channel.split('/')[2])
            except (IndexError, ValueError):
                pass

    return flat


def handle_api_error(error: Exception) -> int:
    """
    Handle API errors and return appropriate exit code.

    Args:
        error: Exception from API call

    Returns:
        int: Exit code (1 for general errors, 2 for auth errors)
    """
    error_str = str(error)

    # Try to extract friendly error message from TransportException
    friendly_message = None
    status_code = None

    # Check if this is a TransportException with JSON error data
    if "TransportException" in error_str:
        # Extract the JSON portion after the colon
        try:
            # Split on "): " to separate headers from JSON body
            parts = error_str.split("): ", 1)
            if len(parts) == 2:
                json_str = parts[1]
                error_data = json.loads(json_str)

                # Extract the friendly error description
                if "error_description" in error_data:
                    friendly_message = error_data["error_description"]
                elif "error" in error_data:
                    friendly_message = error_data["error"]

                # Try to extract status code from headers dict
                if "status" in parts[0]:
                    import re
                    match = re.search(r"'status':\s*'(\d+)'", parts[0])
                    if match:
                        status_code = match.group(1)
        except (json.JSONDecodeError, ValueError, IndexError):
            # If parsing fails, fall back to original error string
            pass

    # Use friendly message if available, otherwise use original error string
    display_error = friendly_message if friendly_message else error_str

    # Determine status code for error categorization
    if not status_code:
        # Fall back to searching in error string
        if "401" in error_str or "unauthorized" in error_str.lower():
            status_code = "401"
        elif "404" in error_str or "not found" in error_str.lower():
            status_code = "404"
        elif "403" in error_str or "forbidden" in error_str.lower():
            status_code = "403"
        elif "420" in error_str or "429" in error_str or "rate limit" in error_str.lower():
            status_code = "429"
        elif "400" in error_str or "bad request" in error_str.lower():
            status_code = "400"

    # Check for authentication errors
    if status_code == "401":
        print_error(
            "Authentication failed. Please check your credentials in .env file."
        )
        return 2

    # Check for not found errors
    if status_code == "404":
        print_error("Resource not found.")
        return 1

    # Check for permission errors
    if status_code == "403":
        print_error("Permission denied or invalid resource ID. Check that the ID is correct and you have access to this resource.")
        return 1

    # Check for rate limiting
    if status_code in ("420", "429"):
        print_error("Rate limit exceeded. Please try again later.")
        return 1

    # Check for validation errors
    if status_code == "400":
        print_error(f"Invalid request: {display_error}")
        return 1

    # Generic error
    print_error(f"API error: {display_error}")
    return 1


def _add_id_alias(item: dict) -> dict:
    """Add a generic 'id' field if a resource-specific ID field exists."""
    if not isinstance(item, dict) or "id" in item:
        return item
    for key in ("app_id", "space_id", "org_id", "task_id", "file_id",
                "comment_id", "hook_id", "conversation_id", "form_id"):
        if key in item:
            item["id"] = item[key]
            break
    return item


def format_response(data: Any) -> Any:
    """
    Format API response data for output.

    Handles common pypodio2 response patterns.

    Args:
        data: Response data from pypodio2

    Returns:
        Formatted data ready for JSON output
    """
    # pypodio2 sometimes returns tuples (response, data)
    if isinstance(data, tuple) and len(data) == 2:
        data = data[1]

    # Add generic 'id' alias for CLI standards
    if isinstance(data, list):
        return [_add_id_alias(item) if isinstance(item, dict) else item for item in data]
    if isinstance(data, dict):
        return _add_id_alias(data)

    return data
