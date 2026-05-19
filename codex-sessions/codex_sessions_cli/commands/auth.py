"""Authentication/status commands for local Codex session data."""
import typer

from ..client import get_client
from .common import emit_one

app = typer.Typer(help="Check Codex local session access", no_args_is_help=True)


@app.command("login")
def login(
    force: bool = typer.Option(False, "--force", "-F", help="Re-check local Codex access"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Report local Codex access; no login is needed for local transcript files."""
    status = get_client().auth_status()
    status["force"] = force
    emit_one(status, table)


@app.command("status")
def status(table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Check whether Codex session data is readable."""
    emit_one(get_client().auth_status(), table)


@app.command("logout")
def logout(table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """No-op logout for local transcript files."""
    status = get_client().auth_status()
    status["authenticated"] = False
    status["message"] = "Codex session transcripts are local files; no credentials were changed."
    emit_one(status, table)
