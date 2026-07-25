"""Generated-history commands for ElevenLabs CLI."""
from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import get_client
from .common import apply_properties, key_value_rows, properties_columns


COMMAND_CREDENTIALS = {"list": ["api_key"], "get": ["api_key"], "download": ["api_key"]}
app = typer.Typer(help="Inspect and download generated history", no_args_is_help=True)


@app.command("list")
@command
def history_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum history items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    page_size: int = typer.Option(100, "--page-size", min=1, max=1000, help="Items requested per API page"),
    start_after_history_item_id: Optional[str] = typer.Option(
        None, "--start-after-history-item-id", help="History item cursor to start after"
    ),
    voice_id: Optional[str] = typer.Option(None, "--voice-id", help="Server-side voice ID filter"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Server-side history search"),
    source: Optional[str] = typer.Option(None, "--source", help="Server-side generation source filter"),
):
    """List generated history items."""
    try:
        items = get_client().list_history(
            limit=limit,
            page_size=page_size,
            start_after_history_item_id=start_after_history_item_id,
            voice_id=voice_id,
            search=search,
            source=source,
            filters=filter,
        )
        output = apply_properties(items, properties)
        if table:
            columns = properties_columns(
                properties, ["history_item_id", "voice_id", "model_id", "state", "date_unix"]
            )
            print_table(output, columns, columns)
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def history_get(
    history_item_id: str = typer.Argument(..., help="History item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one exact generated history item."""
    try:
        output = apply_properties([get_client().get_history_item(history_item_id)], properties)[0]
        if table:
            print_table(key_value_rows(output), ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("download")
@command
def history_download(
    history_item_id: str = typer.Argument(..., help="History item ID"),
    output: Path = typer.Option(..., "--output", "-o", help="Destination audio path"),
):
    """Download audio for one exact generated history item atomically."""
    try:
        print_json(get_client().download_history_audio(history_item_id, output))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
