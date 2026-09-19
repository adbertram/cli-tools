"""Shared rendering and mutation-safeguard helpers for Garrul commands."""

import json
import re
from typing import Callable, List, Optional, Sequence

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.filters import (
    NO_VALUE_OPERATORS,
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    parse_filter_string,
    validate_filters,
)
from cli_tools_shared.output import print_error, print_info, print_json, print_table, print_warning

# C0 and C1 control characters, minus tab and newline. Comment text is written by
# strangers, and a raw ESC byte in a table would let it drive the moderator's terminal.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def filter_fields(filters: Sequence[str]) -> set[str]:
    """Top-level record fields that the --filter expressions read."""
    return {field.split(".")[0] for text in filters for field, _, _ in parse_filter_string(text)}


def validated(filters: Optional[List[str]], fields: Sequence[str]) -> List[str]:
    """Validate --filter up front so a typo never reads as 'nothing matched'."""
    try:
        validate_filters(filters or [])
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    unknown = sorted(filter_fields(filters or []) - set(fields))
    if unknown:
        raise ClientError(f"Cannot filter on {', '.join(unknown)}. Fields: {', '.join(fields)}.")
    return filters or []


def selected(properties: Optional[str], fields: Sequence[str]) -> Optional[List[str]]:
    """Parse --properties. An unknown field is reported on stderr.

    The cli-tools contract is that --properties tolerates a field a record does
    not have (it comes back null), so this warns instead of failing. stdout stays
    data only either way.
    """
    if properties is None:
        return None
    names = [name.strip() for name in properties.split(",") if name.strip()]
    if not names:
        raise ClientError("--properties needs at least one field name.")
    unknown = sorted({name.split(".")[0] for name in names} - set(fields))
    if unknown:
        print_warning(f"No field named {', '.join(unknown)}; it will be null. Fields: {', '.join(fields)}.")
    return names


def server_params(filter_map: FilterMap, filters: List[str]) -> dict:
    """Translate --filter into Garrul query parameters, where that is possible.

    Separate --filter flags are OR'd, which a single query string cannot express,
    so only a lone --filter is pushed to the server. Whatever a clause this does
    NOT cover, `scan_filter` (below) makes `_pages` keep paging for, so the final
    result is exact regardless of whether Garrul or this CLI applied a clause.
    """
    return filter_map.to_api_params(filters) if len(filters) == 1 else {}


def _escape_filter_value(value: Optional[str]) -> str:
    """Re-embed an already-decoded filter value in a fresh field:op:value part.

    Reverses the unescaping `split_filter_parts` does, so a value that itself
    contained a comma or backslash round-trips through `parse_filter_string`
    unchanged instead of being re-split.
    """
    return (value or "").replace("\\", "\\\\").replace(",", "\\,")


def _condition_is_server_pushed(filter_map: FilterMap, field: str, op: str, value: Optional[str]) -> bool:
    """True when this single filter clause, alone, translates to a real API parameter."""
    part = f"{field}:{op}" if op in NO_VALUE_OPERATORS else f"{field}:{op}:{_escape_filter_value(value)}"
    return bool(filter_map.to_api_params([part]))


def scan_filter(filter_map: Optional[FilterMap], filters: List[str]) -> Optional[Callable[[List[dict]], List[dict]]]:
    """Build the post-fetch filter `_pages` needs so --limit bounds the FILTERED result.

    Returns None when there is nothing to filter, or when Garrul's own page is
    already exact (the lone --filter group's every clause was pushed to Garrul
    as a query parameter by `server_params`) -- `_pages` can keep its cheap
    raw-row-count stop in that case. Otherwise returns the same `apply_filters`
    call the caller still makes on the result, so `_pages` pages until --limit
    matches are collected instead of stopping at --limit raw rows and handing
    back fewer matches than actually exist.

    `filter_map` is None for a list command that pushes nothing to the server
    at all (for example `users list`), so every filter on it is always
    client-side and never fully covered.
    """
    if not filters:
        return None
    if filter_map is not None and len(filters) == 1:
        conditions = parse_filter_string(filters[0])
        if conditions and all(_condition_is_server_pushed(filter_map, field, op, value) for field, op, value in conditions):
            return None
    return lambda rows: apply_filters(rows, filters)


def _cell(value):
    if isinstance(value, str):
        return _CONTROL.sub(lambda match: f"\\x{ord(match.group()):02x}", value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=True)
    return value


def emit_rows(
    rows: List[dict],
    filters: List[str],
    limit: int,
    table: bool,
    names: Optional[List[str]],
    columns: List[str],
    empty: str,
) -> None:
    """Filter, then cut to --limit, then project. In that order, so a limit never hides a match."""
    if limit < 1:
        raise ClientError("--limit must be at least 1.")
    if filters:
        rows = apply_filters(rows, filters)
    rows = rows[:limit]
    if names:
        rows = apply_properties_filter(rows, ",".join(names))
        columns = names
    if not table:
        print_json(rows)
    elif not rows:
        print_info(empty)
    else:
        safe = [{key: _cell(value) for key, value in row.items()} for row in rows]
        print_table(safe, columns, [column.replace("_", " ").title() for column in columns])


def emit_record(record: dict, table: bool, properties: Optional[str] = None) -> None:
    names = selected(properties, list(record))
    if names:
        record = apply_properties_filter([record], ",".join(names))[0]
    if table:
        rows = [{"field": key, "value": _cell(value)} for key, value in record.items()]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(record)


def page_hint(result: dict, limit: int) -> None:
    """Tell the operator on stderr how to reach the rows this call did not return."""
    if result["next_before"] is not None:
        print_info(f"More rows exist. Next page: --before '{result['next_before']}'")
    elif result["more"]:
        print_info(f"More rows exist. Garrul only issues cursors every 50 rows, so re-run with a --limit above {limit}.")


def mutate(action: str, request: dict, yes: bool, dry_run: bool, call: Callable[[], dict]) -> None:
    """The single gate every state-changing command goes through.

    --dry-run prints the exact request and sends nothing (no credentials needed).
    Anything else must carry --yes, so an agent or a pipe can never mutate a
    comment system by accident.
    """
    if yes and dry_run:
        raise ClientError("Pass either --yes or --dry-run, not both.")
    if dry_run:
        print_json({"dry_run": True, "action": action, **request})
        return
    if not yes:
        raise ClientError(f"Refusing to {action} without --yes or --dry-run.")
    print_json(call())
