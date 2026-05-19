"""User account commands for ElevenLabs CLI."""
COMMAND_CREDENTIALS = {
    "subscription": ["api_key"],
}

from typing import Optional

import typer
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client
from .common import apply_properties, key_value_rows


app = typer.Typer(help="Inspect ElevenLabs user account data", no_args_is_help=True)


@app.command("subscription")
def user_subscription(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get the current user subscription and quota state."""
    try:
        subscription = get_client().get_subscription()
        output = apply_properties([subscription], properties)[0]
        if table:
            print_table(key_value_rows(output), ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
