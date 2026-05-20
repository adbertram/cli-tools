"""Slack app verification commands."""
import typer

from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client

app = typer.Typer(help="Verify and test the Cody Slack app", no_args_is_help=True)


@app.command("verify")
def verify(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Verify Cody's Slack app bot."""
    try:
        result = get_client().slack_verify()
        if table:
            rows = [
                {
                    "id": result.bot_user.id,
                    "name": result.bot_user.name,
                    "deleted": result.bot_user.deleted,
                    "is_bot": result.bot_user.is_bot,
                }
            ]
            print_table(rows, ["id", "name", "deleted", "is_bot"], ["ID", "Name", "Deleted", "Bot"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send-test")
def send_test(
    text: str = typer.Argument(..., help="Message text to send to Adam's Cody app DM"),
):
    """Send a test message from the Cody app into Adam's Cody DM."""
    try:
        print_json(get_client().send_test_message(text))
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "send-test": [
        "custom"
    ],
    "verify": [
        "custom"
    ]
}
