"""Entry commands — query parsed log entries from packages."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from ..filters import apply_filters  # client-side filtering on local JSONL
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Query parsed log entries", no_args_is_help=True)


def _model_to_dict(item):
    """Convert model or dict to dict."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def _extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items."""
    result = []
    for item in items:
        data = _model_to_dict(item)
        extracted = {}
        for field in fields:
            parts = field.split(".")
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def entries_list(
    package: str = typer.Argument(..., help="Package name to query"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum entries to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f",
        help="Filter: field:op:value (e.g., level:eq:ERROR, entity:eq:app_log)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p",
        help="Comma-separated fields to include"),
):
    """
    List log entries from a package.

    All filtering is client-side on local JSONL data.

    Examples:
        azlogs entries list 2026-02-10_09-40-16
        azlogs entries list 2026-02-10_09-40-16 --table --limit 20
        azlogs entries list 2026-02-10_09-40-16 --filter "level:eq:ERROR"
        azlogs entries list 2026-02-10_09-40-16 --filter "entity:eq:app_log"
        azlogs entries list 2026-02-10_09-40-16 --filter "service:ilike:%automation%"
        azlogs entries list 2026-02-10_09-40-16 --filter "level:eq:ERROR" --filter "level:eq:WARNING"
        azlogs entries list 2026-02-10_09-40-16 --properties "timestamp,level,service,message"
    """
    try:
        client = get_client()
        entries = client.list_entries(package=package, limit=limit, filters=filter)

        # Apply properties selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            entries = _extract_fields(entries, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(entries, fields, fields)
            else:
                # Default table columns for readability
                print_table(
                    entries,
                    ["timestamp", "entity", "level", "service", "message"],
                    ["Timestamp", "Entity", "Level", "Service", "Message"],
                )
        else:
            print_json(entries)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def entries_get(
    package: str = typer.Argument(..., help="Package name"),
    source_file: str = typer.Argument(..., help="Source file path within package"),
    line_number: int = typer.Argument(..., help="Line number in source file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific log entry by source file and line number.

    Examples:
        azlogs entries get 2026-02-10_09-40-16 "LogFiles/ciem.log" 42
        azlogs entries get 2026-02-10_09-40-16 "LogFiles/ciem.log" 42 --table
    """
    try:
        client = get_client()
        entry = client.get_entry(package, source_file, line_number)

        if table:
            item_dict = _model_to_dict(entry)
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(entry)

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
