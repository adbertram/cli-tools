"""Click commands."""
from typing import Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, read_json_body


COMMAND_CREDENTIALS = {"retrieve": ["custom"], "export": ["custom"]}

app = typer.Typer(help="Retrieve and export click data", no_args_is_help=True)


@app.command("retrieve")
def clicks_retrieve(click_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one click."""
    try:
        output_item(get_client().get_click(click_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("export")
def clicks_export(
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON query parameter file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Export clicks."""
    try:
        output_item(get_client().export_clicks(read_json_body(json_file)), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
