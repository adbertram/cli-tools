"""Configuration inspection commands."""
import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client

app = typer.Typer(help="Show Cody bridge configuration", no_args_is_help=True)


@app.command("show")
def show(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Show configured Cody bridge paths and identifiers."""
    try:
        result = get_client().config_status()
        if table:
            print_table(
                [result],
                ["app_id", "bot_user_id", "dm_channel_id", "config_path"],
                ["App ID", "Bot User", "DM Channel", "Config"],
            )
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "show": [
        "custom"
    ]
}
