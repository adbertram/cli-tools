"""Authentication commands for Monarch CLI."""
import sys

import typer

from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config
from ..client import MonarchClient, ClientError


def _login_handler(config, force: bool):
    """Custom login handler for Monarch Money email/password/MFA flow.

    MFA handling priority:
    1. MFA_SECRET in .env as a TOTP secret (base32) -> client auto-generates codes
    2. MFA_SECRET in .env as a one-time code (numeric) -> used directly
    3. Interactive prompt for a one-time MFA code, when stdin is a TTY and neither
       of the above is configured. This is the no-persistent-secret path: the code
       is typed once at login time and never stored.

    When Monarch requires MFA, no MFA_SECRET is configured, and stdin is not a TTY
    (a headless/automated caller), the handler fails clearly with a ClientError
    instead of blocking on an interactive prompt.
    """
    client = MonarchClient(config=config)

    if force:
        config.clear_session()

    # First attempt relies on config's MFA_SECRET (TOTP secret or one-time code,
    # handled inside client.login). mfa_code=None means "no interactively-typed
    # code yet".
    result = client.login(
        email=config.username,
        password=config.password,
        mfa_code=None,
    )

    if result.get("mfa_required"):
        if not sys.stdin.isatty():
            raise ClientError(
                "MFA is required. Set MFA_SECRET to a TOTP secret or one-time code, "
                "or rerun 'monarch auth login' in an interactive terminal to enter a code."
            )
        code = typer.prompt("Enter Monarch MFA code")
        result = client.login(
            email=config.username,
            password=config.password,
            mfa_code=code,
        )

    if not result["success"]:
        raise ClientError(result.get("message", "Login failed"))


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="monarch",
    login_handler=_login_handler,
)
