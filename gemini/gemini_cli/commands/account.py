"""Account commands for Gemini CLI."""
import webbrowser

import typer
from cli_tools_shared.output import command, print_info

COMMAND_CREDENTIALS = {"topup": ["no_auth"]}

app = typer.Typer(help="Manage the Gemini API account and billing")

# URL named by the Gemini API's own "prepayment credits are depleted" error.
TOPUP_URL = "https://ai.studio/projects"


@app.command("topup")
@command
def account_topup(
    no_open: bool = typer.Option(False, "--no-open", help="Only print the URL; do not open a browser"),
):
    """
    Open the AI Studio page where prepaid Gemini API credits are added.

    Makes no Gemini API call, so it works when credits are depleted.

    Example:
        gemini-api account topup
        gemini-api account topup --no-open
    """
    typer.echo(TOPUP_URL)
    if not no_open:
        webbrowser.open(TOPUP_URL)
        print_info("Opened in the default browser")
