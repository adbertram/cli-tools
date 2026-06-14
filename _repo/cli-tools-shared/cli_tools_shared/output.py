"""Output formatting helpers.

Stream Usage:
    stdout (fd 1) -> Data only (JSON, tables) - via print_json(), print_table()
    stderr (fd 2) -> Messages only - via print_error(), print_warning(), print_success(), print_info()

This separation enables clean piping: `<tool> list | jq '.field'`
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table
from rich import box

from .exceptions import ClientError, CredentialError


def _stdout_is_interactive_tty() -> bool:
    """Return True only when stdout is a real interactive terminal.

    Color and terminal control sequences (including Rich's terminal
    background/theme detection, which round-trips an OSC 11 response) must only
    be emitted to an interactive terminal. When stdout is a pipe or file, or a
    PTY-backed capture sets FORCE_COLOR / TTY_COMPATIBLE to fake a terminal, the
    answer is still "not interactive" for our purposes: automation parses this
    stream as data and any escape byte corrupts it.
    """
    isatty = getattr(sys.stdout, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except ValueError:
        # isatty() can raise on a closed stream (e.g. at pytest teardown).
        return False


def _color_disabled_by_env() -> bool:
    """Return True when the environment opts out of color.

    Honors the https://no-color.org convention (any non-empty NO_COLOR) and the
    conventional TERM=dumb signal for non-capable terminals.
    """
    if os.environ.get("NO_COLOR", "") != "":
        return True
    if os.environ.get("TERM", "").strip().lower() == "dumb":
        return True
    return False


def _build_console() -> Console:
    """Build the shared Rich console with deterministic color/escape gating.

    stdout carries DATA. Color and any terminal control sequence are emitted
    only when stdout is a genuine interactive TTY and the environment has not
    opted out of color. Otherwise the console is forced into a plain,
    no-color, non-terminal mode so it never writes ANSI styling or terminal
    detection escapes into captured output. This is the single source of
    color/escape policy for every CLI tool.
    """
    if _stdout_is_interactive_tty() and not _color_disabled_by_env():
        return Console()
    # force_terminal=False stops Rich from honoring FORCE_COLOR / TTY_COMPATIBLE
    # and from running terminal background/theme detection; no_color=True
    # guarantees no ANSI styling even if something downstream flips detection.
    return Console(force_terminal=False, no_color=True)


# Rich console for table output. Gated so non-TTY stdout never receives color
# or terminal control/detection escape sequences.
console = _build_console()


def _supports_unicode() -> bool:
    """Check if the current stdout encoding supports common Unicode symbols.

    Returns False on Windows when the console uses a legacy encoding (e.g.
    cp1252) that cannot represent characters like U+2713 (checkmark).
    """
    if os.name != "nt":
        return True
    encoding = getattr(sys.stdout, "encoding", None) or ""
    return encoding.lower().replace("-", "") in ("utf8", "utf16")


# ASCII-safe symbol alternatives for environments that lack Unicode support.
_SYMBOLS_UNICODE = {"check": "\u2713", "cross": "\u2717", "warning": "\u26a0", "circle": "\u25cb"}
_SYMBOLS_ASCII = {"check": "Yes", "cross": "No", "warning": "(!)", "circle": "-"}


def safe_symbol(name: str) -> str:
    """Return a display symbol that is safe for the current terminal encoding.

    Supported names: ``check``, ``cross``, ``warning``, ``circle``.
    """
    symbols = _SYMBOLS_UNICODE if _supports_unicode() else _SYMBOLS_ASCII
    return symbols.get(name, name)


def _format_cell_value(value: Any) -> str:
    """Format a cell value for table display."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return safe_symbol("check") if value else safe_symbol("cross")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def print_table(
    data: Optional[Union[Sequence[Union[BaseModel, dict]], dict]],
    columns: Optional[List[str]] = None,
    headers: Optional[List[str]] = None,
    title: Optional[str] = None,
    max_columns: int = 6,
):
    """Print data as a Rich formatted table to stdout.

    Handles Pydantic models, dicts, and lists of either.
    Uses Rich tables with box-drawing characters for better visual output.
    Limits display to max ``max_columns`` columns for readability.

    Args:
        data: Data to output as table (list of dicts/models or single dict/model).
        columns: Optional list of column keys to display. If None, auto-discovers.
        headers: Optional display headers (defaults to column names).
        title: Optional table title.
        max_columns: Maximum number of columns to display. Defaults to 6.
            Pass 0 to disable the limit and show all columns.
    """
    if data is None:
        console.print("[dim]No data[/dim]")
        return

    # Handle wrapped responses (e.g., {items: [...], total: N})
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        data = data["items"]

    # Convert single item to list
    if isinstance(data, (dict, BaseModel)):
        data = [data]

    if not data:
        console.print("[dim]No data[/dim]")
        return

    # Convert models to dicts (mode="json" serializes enums to values)
    rows: List[Dict] = []
    for item in data:
        if isinstance(item, BaseModel):
            rows.append(item.model_dump(mode="json"))
        elif isinstance(item, dict):
            rows.append(item)
        else:
            rows.append({"value": item})

    if not rows:
        console.print("[dim]No data[/dim]")
        return

    # Auto-discover columns if not provided
    if columns is None:
        all_keys: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in all_keys:
                    all_keys.append(key)
        columns = all_keys

    if not columns:
        console.print("[dim]No data[/dim]")
        return

    # Limit columns for readability (max_columns=0 disables the limit)
    if max_columns > 0 and len(columns) > max_columns:
        columns = columns[:max_columns]

    # Use column names as headers if not provided
    if headers is None:
        headers = columns
    elif max_columns > 0 and len(headers) > max_columns:
        headers = headers[:max_columns]

    # Create Rich table with box-drawing characters
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        box=box.HEAVY_HEAD,
    )

    # Add columns - allow wrapping for long values
    for header, col in zip(headers, columns):
        table.add_column(header, no_wrap=False)

    # Add rows
    for row in rows:
        row_values = []
        for col in columns:
            value = row.get(col, "")
            row_values.append(_format_cell_value(value))
        table.add_row(*row_values)

    console.print(table)


def _sanitize_surrogates(s: str) -> str:
    """Remove surrogate characters from a string.

    Surrogate pairs (U+D800-U+DFFF) are invalid in isolation and cause
    UnicodeEncodeError when printing to stdout. This encodes with
    'surrogatepass' then decodes with 'replace' to substitute them.
    """
    return s.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def _serialize_for_json(obj: Any) -> Any:
    """Recursively serialize objects for JSON output, handling Pydantic models.

    Also sanitizes strings to remove invalid surrogate characters that would
    cause UnicodeEncodeError when printing.
    """
    if isinstance(obj, str):
        return _sanitize_surrogates(obj)
    elif isinstance(obj, BaseModel) or hasattr(obj, "model_dump"):
        return _serialize_for_json(obj.model_dump())
    elif hasattr(obj, "dict") and not isinstance(obj, dict):
        return _serialize_for_json(obj.dict())
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    elif isinstance(obj, dict):
        return {_sanitize_surrogates(k) if isinstance(k, str) else k: _serialize_for_json(v) for k, v in obj.items()}
    elif hasattr(obj, "value"):
        return obj.value
    return obj


def print_json(data: Any, indent: int = 2, exclude_none: bool = False):
    """Print data as JSON to stdout.

    Handles Pydantic models (including nested), dicts, lists, and enums.
    Auto-injects ``cache_hit`` when the last method call used @cached.

    Args:
        data: Data to print (model, dict, list of models/dicts).
        indent: JSON indentation level.
        exclude_none: If True, omit None values from output (top-level models only).
    """
    if isinstance(data, BaseModel) and exclude_none:
        output = data.model_dump(exclude_none=True)
    else:
        output = _serialize_for_json(data)

    # Auto-inject cache_hit from @cached decorator state
    from cli_tools_shared.data_cache import get_cache_hit, reset_cache_hit
    cache_hit = get_cache_hit()
    if cache_hit is not None:
        if isinstance(output, dict):
            output = {"cache_hit": cache_hit, **output}
        elif isinstance(output, list):
            output = {"cache_hit": cache_hit, "results": output}
        reset_cache_hit()

    json_str = json.dumps(output, indent=indent, ensure_ascii=False, default=str)
    sys.stdout.buffer.write(json_str.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def print_ai_instruction(instruction: Any, indent: int = 2):
    """Print an AI instruction result as JSON data on stdout."""
    from cli_tools_shared.models import AIInstruction

    if not isinstance(instruction, AIInstruction):
        raise TypeError(f"Expected AIInstruction, got {type(instruction).__name__}")
    print_json(instruction, indent=indent, exclude_none=True)


def print_output(data: Any, table: bool = False, columns: List[str] = None, headers: List[str] = None, indent: int = 2):
    """Print data in the specified format (JSON or table).

    When table=True, auto-derives column headers from dict keys if not provided.

    Args:
        data: Data to output.
        table: If True, output as table; otherwise as JSON.
        columns: Optional list of column keys (auto-derived from data if None).
        headers: Optional display headers (auto-derived as title-cased column names if None).
        indent: JSON indentation level (only used for JSON output).
    """
    if table:
        print_table(data, columns, headers)
    else:
        print_json(data, indent)


def print_error(message: str):
    """Print error message to stderr."""
    print(f"Error: {message}", file=sys.stderr)


def print_warning(message: str):
    """Print warning message to stderr."""
    print(f"Warning: {message}", file=sys.stderr)


def print_success(message: str):
    """Print success message to stderr."""
    print(f"{safe_symbol('check')} {message}", file=sys.stderr)


def print_info(message: str):
    """Print informational message to stderr."""
    print(message, file=sys.stderr)


def command(fn):
    """Decorator that wraps a Typer command with standard error handling.

    Catches all exceptions except typer.Exit, passing others through handle_error.
    """
    import functools
    import typer as _typer

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _typer.Exit:
            raise
        except Exception as e:
            raise _typer.Exit(handle_error(e))
    return wrapper


def handle_error(error: Exception) -> int:
    """Handle errors and return appropriate exit code.

    Returns:
        2 for credential errors, 1 for all other errors.
    """
    print_error(str(error))
    if isinstance(error, CredentialError):
        return 2
    return 1
