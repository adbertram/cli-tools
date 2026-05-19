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
from typing import Optional
import sys


# --- CLI-specific helpers ---


def print_mandatory_review(
    title: str,
    action: str,
    reason: str,
    preview: str | None = None,
):
    """Print a prominent mandatory review warning box.

    Args:
        title: What needs review (e.g., "Action Summary", "Script")
        action: What must be done (e.g., "update to match the new Script")
        reason: Why this is required
        preview: Optional preview of the existing content
    """
    red = "\033[91m"
    yellow = "\033[93m"
    bold = "\033[1m"
    reset = "\033[0m"

    print("", file=sys.stderr)
    print(f"{red}{bold}{'─' * 70}{reset}", file=sys.stderr)
    print(f"{red}{bold}🛑 MANDATORY REVIEW: {title}{reset}", file=sys.stderr)
    print(f"{red}{bold}{'─' * 70}{reset}", file=sys.stderr)
    print(f"{yellow}   Action Required: {action}{reset}", file=sys.stderr)
    print(f"   Reason: {reason}", file=sys.stderr)
    if preview:
        truncated = f"{preview[:80]}..." if len(preview) > 80 else preview
        print(f"   Preview: {truncated}", file=sys.stderr)
    print(f"{red}{bold}{'─' * 70}{reset}", file=sys.stderr)
    print("", file=sys.stderr)
