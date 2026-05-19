"""Output formatting helpers.

Re-exports standard output functions from cli_tools_shared.output.
CLI-specific helpers defined below.

Stream Usage:
    stdout (fd 1) -> Data only (JSON, tables) - via print_json(), print_table()
    stderr (fd 2) -> Messages only - via print_error(), print_warning(), print_success(), print_info()
"""

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
import sys


# --- CLI-specific helpers ---


def print_status(message: str):
    """Print status/progress message to stderr."""
    print(message, file=sys.stderr)
