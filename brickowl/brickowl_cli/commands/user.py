"""User commands for Brickowl CLI."""
COMMAND_CREDENTIALS = {
    "details": ["api_key"],
}

import typer

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="View Brick Owl user details", no_args_is_help=True)


@app.command("details")
def user_details(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get your Brick Owl user/store details.

    Examples:
        brickowl user details
        brickowl user details --table
    """
    try:
        client = get_client()
        user = client.get_user_details()

        if table:
            user_dict = user.model_dump(mode="json")
            rows = [{"field": k, "value": str(v)} for k, v in user_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(user)

    except Exception as e:
        raise typer.Exit(handle_error(e))
