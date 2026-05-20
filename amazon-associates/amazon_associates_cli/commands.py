"""Program metadata commands for AmazonAssociates CLI."""

import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from .client import get_client

app = typer.Typer(help="Show verified metadata for the affiliate program", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "info": ["browser_session"],
}


@app.command("info")
def program_info(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show verified metadata for this CLI.

    Examples:
        amazon-associates program info
        amazon-associates program info --table
    """
    try:
        info = get_client().get_program_info()
        if table:
            rows = [
                {"field": field, "value": "" if value is None else str(value)}
                for field, value in info.model_dump().items()
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
            return

        print_json(info)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
