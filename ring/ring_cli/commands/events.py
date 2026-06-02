"""Events commands — list and download Ring history (dings, motion, on-demand)."""
from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    apply_filters,
    apply_limit,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import (
    handle_error,
    print_json,
    print_table,
)

from ..client import get_client
from ..models import EventKind


app = typer.Typer(help="List and download Ring events (dings, motion)", no_args_is_help=True)


COMMAND_CREDENTIALS = {
    "list": ["username_password"],
    "get": ["username_password"],
    "download": ["username_password"],
}





def _parse_kind(value: Optional[str]) -> Optional[EventKind]:
    if value is None:
        return None
    try:
        return EventKind(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"Invalid --kind '{value}'. Valid values: {', '.join(k.value for k in EventKind)}"
        ) from exc


@app.command("list")
def events_list(
    device: Optional[str] = typer.Option(
        None, "--device", "-d", help="Limit to a single device (name or numeric ID)"
    ),
    kind: Optional[str] = typer.Option(
        None, "--kind", "-k", help=f"Filter by event kind ({', '.join(k.value for k in EventKind)})"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(25, "--limit", "-l", help="Maximum events per device"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """List recent Ring events.

    Examples:
        ring events list
        ring events list --device "Front Door"
        ring events list --kind motion --limit 50
        ring events list --device "Back Yard" --kind ding --table
    """
    try:
        if filter:
            validate_filters(filter)

        client = get_client()
        events = client.list_events(identifier=device, limit=limit, kind=_parse_kind(kind))

        if filter:
            events = apply_filters(events, filter)
        events = apply_limit(events, limit)
        if properties:
            events = apply_properties_filter(events, properties)

        if table:
            columns = (
                [c.strip() for c in properties.split(",")]
                if properties
                else ["id", "device_name", "kind", "created_at", "answered"]
            )
            print_table(events, columns, columns)
        else:
            print_json(events)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def events_get(
    event_id: str = typer.Argument(..., help="Event ID (from `events list`)"),
    device: str = typer.Option(
        ..., "--device", "-d", help="Device name or numeric ID the event belongs to"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Look up a single event by ID under a specific device.

    Ring's history endpoint is per-device, so we scan the last 200 events
    on the given device and return the matching entry.
    """
    try:
        client = get_client()
        events = client.list_events(identifier=device, limit=200, kind=None)
        matches = [e for e in events if str(e.id) == str(event_id)]
        if not matches:
            from cli_tools_shared.exceptions import ClientError
            raise ClientError(
                f"Event id '{event_id}' not found in the last 200 events for device '{device}'."
            )
        event = matches[0]
        if properties:
            event = apply_properties_filter([event], properties)[0]

        if table:
            data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
            rows = [{"field": k, "value": str(v)} for k, v in data.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(event)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("download")
def events_download(
    event_id: Optional[str] = typer.Argument(
        None, help="Event ID to download. Omit with --recent to grab the last N events."
    ),
    device: str = typer.Option(
        ..., "--device", "-d", help="Device name or numeric ID the event belongs to"
    ),
    recent: Optional[int] = typer.Option(
        None,
        "--recent",
        "-r",
        help="Download the most recent N events instead of a specific event_id",
    ),
    kind: Optional[str] = typer.Option(
        None, "--kind", "-k", help="Restrict --recent to a single kind (ding, motion, ...)"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Destination directory (default: ~/Downloads/ring/)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Download recordings as MP4 files.

    Examples:
        ring events download EVENT_ID --device "Front Door"
        ring events download --device "Front Door" --recent 5
        ring events download --device "Back Yard" --recent 10 --kind motion --output ./clips
    """
    try:
        client = get_client()

        if recent is not None and event_id is not None:
            raise typer.BadParameter("Use either EVENT_ID or --recent, not both.")
        if recent is None and event_id is None:
            raise typer.BadParameter("Provide an EVENT_ID, or use --recent N.")

        if recent is not None:
            results = client.download_recent(
                identifier=device,
                count=recent,
                kind=_parse_kind(kind),
                output_dir=output,
            )
        else:
            results = [client.download_event(identifier=device, event_id=event_id, output_dir=output)]

        if table:
            columns = ["event_id", "device_name", "kind", "created_at", "path", "size_bytes"]
            print_table(results, columns, columns)
        else:
            print_json(results)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
