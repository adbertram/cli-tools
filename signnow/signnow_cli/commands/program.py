"""Program metadata commands for signNow CLI."""

import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client

app = typer.Typer(help="Show verified metadata for the developer platform", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "info": ["oauth"],
}


@app.command("info")
def program_info(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show verified metadata for this CLI.

    Examples:
        signnow program info
        signnow program info --table
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
