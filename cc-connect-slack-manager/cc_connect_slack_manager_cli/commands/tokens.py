"""Keychain token status commands."""
import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client

app = typer.Typer(help="Check Cody Slack token presence", no_args_is_help=True)


@app.command("status")
def status(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show whether required Slack tokens exist in Keychain."""
    try:
        result = get_client().token_status()
        if table:
            print_table(result, ["service", "account", "present"], ["Service", "Account", "Present"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "status": [
        "custom"
    ]
}
