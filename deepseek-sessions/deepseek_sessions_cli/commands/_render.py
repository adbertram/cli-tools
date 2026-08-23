"""Shared post-processing and table formatting for list commands.

Each list command applies `--filter` itself with the shared `apply_filters`, so
the filtering is visible at the command site. This module owns what is purely
presentational: `--properties` selection and table column formatting.
"""
import json
from typing import Any, Dict, List, Optional, Sequence

from cli_tools_shared.output import print_table

from ..parsers import format_local_time

# Table timestamps carry the date because these tools are queried across days.
TABLE_TIME_FORMAT = "%m%d-%H%M"


def to_items(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Convert Pydantic model rows to plain dicts for filtering and output."""
    return [row.model_dump() for row in rows]


# A client-side --filter must run against the whole result set, so a filtered
# list fetches wide and applies --limit only after filtering. Without this,
# `--limit 2 --filter X` returns fewer than 2 rows whenever the first 2 rows do
# not match.
UNBOUNDED = 1_000_000


def fetch_limit(limit: int, filter: object) -> int:
    """Rows to request from the client, given a possibly-filtered request."""
    return UNBOUNDED if filter else limit


def select_properties(
    items: List[Dict[str, Any]],
    properties: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Reduce each row to the comma-separated fields named by `--properties`."""
    if not properties:
        return items
    wanted = {name.strip() for name in properties.split(",") if name.strip()}
    return [
        {key: value for key, value in item.items() if key in wanted} for item in items
    ]


def add_time(
    items: List[Dict[str, Any]],
    source: str,
    target: str,
    format: str = TABLE_TIME_FORMAT,
) -> None:
    """Add a local-time display column derived from an ISO field."""
    for item in items:
        item[target] = format_local_time(item.get(source, "") or "", format)


def add_tokens(items: List[Dict[str, Any]]) -> None:
    """Add thousands-separated token columns, blank when zero.

    Column names match the dsh usage counters: uncached input, output, cache
    reads, the reasoning subset of output, and the weighted effective total.
    """
    columns = {
        "in_tok": "total_input_tokens",
        "out_tok": "total_output_tokens",
        "cache_read": "total_cache_read_tokens",
        "reasoning": "total_reasoning_tokens",
        "effective": "effective_tokens",
    }
    for item in items:
        for target, source in columns.items():
            value = item.get(source, 0) or 0
            item[target] = f"{value:,}" if value else ""


def blank_none(items: List[Dict[str, Any]], *fields: str) -> None:
    """Replace None with an empty string so table cells render clean."""
    for item in items:
        for field in fields:
            item[field] = item.get(field) or ""


def render_table(
    items: List[Dict[str, Any]],
    lean: Sequence[tuple],
    extra: Sequence[tuple] = (),
    wide: bool = False,
) -> None:
    """Print a table with a readable default and a full `--wide` variant.

    `lean` and `extra` are sequences of `(column_key, header)` pairs. The lean
    set alone renders by default so the table stays legible in a normal
    terminal; `--wide` appends `extra` and lifts the column cap.
    """
    pairs = list(lean) + (list(extra) if wide else [])
    columns = [column for column, _ in pairs]
    headers = [header for _, header in pairs]
    print_table(items, columns, headers, max_columns=0)


def truncate_value(value: Any, max_length: int = 40) -> str:
    """Render any value as a single-line string bounded to max_length."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, separators=(",", ":"), default=str)
    else:
        text = str(value)
    text = text.replace("\n", " ").replace("\r", "")
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def format_status(status: Any) -> str:
    """Render a status as a compact symbol for table output."""
    if hasattr(status, "value"):
        status = status.value
    symbols = {"error": "✗", "success": "✓", "invoked": "→", "pending": "…"}
    return symbols.get(status, status or "")


def format_event_type(event_type: Any) -> str:
    """Shorten a timeline event type for table output."""
    if hasattr(event_type, "value"):
        event_type = event_type.value
    labels = {
        "user_message": "user",
        "assistant_message": "assistant",
        "thinking": "thinking",
        "notice": "notice",
        "skill_load": "skill",
        "command": "command",
        "tool_call": "tool",
        "code_dispatch": "code",
        "subagent_start": "agent_invocation",
        "subagent_tool": "agent_tool",
        "todo_write": "todos",
        "goal_change": "goal",
        "approval": "approval",
        "retry": "retry",
        "compaction": "compaction",
        "turn_end": "turn_end",
        "error": "error",
    }
    return labels.get(event_type, event_type or "")
