"""Model commands for ElevenLabs CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client
from .common import apply_properties, key_value_rows, properties_columns


app = typer.Typer(help="Manage ElevenLabs models", no_args_is_help=True)


@app.command("list")
def models_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum models to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., model_id:eq:eleven_multilingual_v2, can_do_text_to_speech:eq:true)",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List available models."""
    try:
        models = get_client().list_models(limit=limit, filters=filter)
        output = apply_properties(models, properties)
        if table:
            columns = properties_columns(
                properties,
                ["model_id", "name", "can_do_text_to_speech", "maximum_text_length_per_request"],
            )
            print_table(output, columns, columns)
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def models_get(
    model_id: str = typer.Argument(..., help="Model ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a model from the model list by ID."""
    try:
        matches = get_client().list_models(limit=1000, filters=[f"model_id:eq:{model_id}"])
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one model for model_id '{model_id}', got {len(matches)}")
        model = matches[0]
        output = apply_properties([model], properties)[0]
        if table:
            print_table(key_value_rows(output), ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
