"""TikTok-only manual opt-in around the shared authentication command."""

from typing import Optional

import typer
from cli_tools_shared.output import command

from .browser import manual_login_requested
from .config import BROWSER_AUTH_TYPE


def add_manual_login_option(app):
    """Extend only the login callback of an existing shared authentication app."""
    login_command = next(info for info in app.registered_commands if info.name == "login")
    shared_login = login_command.callback

    @command
    def auth_login(
        profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Profile name to save credentials to"),
        force: bool = typer.Option(False, "--force", "-F", help="Clear existing ephemeral auth state and re-authenticate"),
        credential_type: Optional[str] = typer.Option(None, "--credential-type", "--credential", "-c", help="Authenticate only 'custom' or 'browser_session'"),
        manual: bool = typer.Option(False, "--manual", help="Open plain visible Chrome for manual login in an isolated named browser_session profile; never submit stored credentials"),
    ):
        """Configure authentication, optionally using a manual browser login.

        With --manual, finish login in the opened Chrome window and press Enter
        here. Without a terminal, close that window within five minutes instead.
        The shared engine verifies live authentication and persists the session.
        """
        if manual:
            if not profile or profile.strip().lower() == "default":
                raise typer.BadParameter("--manual requires an explicit non-default --profile")
            if credential_type not in (BROWSER_AUTH_TYPE, "browser"):
                raise typer.BadParameter("--manual requires --credential-type browser_session")
        token = manual_login_requested.set(manual)
        try:
            return shared_login(profile=profile, force=force, credential_type=credential_type)
        finally:
            manual_login_requested.reset(token)

    login_command.callback = auth_login
    return app
