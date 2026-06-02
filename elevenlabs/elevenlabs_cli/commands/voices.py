"""Voice commands for ElevenLabs CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
    "settings": ["api_key"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client
from .common import apply_properties, key_value_rows, properties_columns


app = typer.Typer(help="Manage ElevenLabs voices", no_args_is_help=True)


@app.command("list")
def voices_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", min=1, max=1000, help="Maximum voices to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%Rachel%, category:eq:generated)",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Server-side search across voice metadata"),
    voice_type: Optional[str] = typer.Option(None, "--voice-type", help="Voice type filter"),
    category: Optional[str] = typer.Option(None, "--category", help="Voice category filter"),
    sort: Optional[str] = typer.Option(None, "--sort", help="Sort field: created_at_unix or name"),
    sort_direction: Optional[str] = typer.Option(None, "--sort-direction", help="Sort direction: asc or desc"),
):
    """List available voices."""
    try:
        voices = get_client().list_voices(
            limit=limit,
            filters=filter,
            search=search,
            voice_type=voice_type,
            category=category,
            sort=sort,
            sort_direction=sort_direction,
        )
        output = apply_properties(voices, properties)
        if table:
            columns = properties_columns(properties, ["voice_id", "name", "category", "description"])
            print_table(output, columns, columns)
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def voices_get(
    voice_id: str = typer.Argument(..., help="Voice ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get metadata for a voice."""
    try:
        voice = get_client().get_voice(voice_id)
        output = apply_properties([voice], properties)[0]
        if table:
            print_table(key_value_rows(output), ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("settings")
def voices_settings(
    voice_id: str = typer.Argument(..., help="Voice ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get stored settings for a voice."""
    try:
        settings = get_client().get_voice_settings(voice_id)
        output = apply_properties([settings], properties)[0]
        if table:
            print_table(key_value_rows(output), ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
