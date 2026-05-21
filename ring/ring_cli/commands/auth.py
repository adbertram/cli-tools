"""Authentication commands for Ring CLI.

This CLI uses the auth contract exposed by ``python-ring-doorbell``:
``Auth.async_fetch_token(username, password, otp_code=None)``. It does not use
Ring Partner API client credentials or hosted OAuth/account-linking endpoints.

The shared ``create_auth_app`` from ``cli_tools_shared`` handles prompting for
``USERNAME`` and ``PASSWORD``, then delegates token acquisition to
``_login_handler``. The SDK only sends the 2FA code after the token exchange
starts, so the OTP read happens inside the SDK callback.
"""
import sys

from cli_tools_shared.auth_commands import create_auth_app
import typer

from ..client import RingClient
from ..config import get_config


def _read_otp_code() -> str:
    typer.echo("Enter Ring 2FA code: ", nl=False, err=True)
    code = sys.stdin.readline().strip()
    if not code:
        raise typer.BadParameter("Ring 2FA code is required")
    return code


def _login_handler(config, force: bool):
    """Custom login handler for ring-doorbell's consumer OAuth + 2FA flow.

    ``create_auth_app`` has already prompted for USERNAME and PASSWORD.
    The Ring SDK triggers MFA during token exchange, then calls the OTP
    callback so the prompt happens after Ring has sent the code.
    """
    if force:
        config.clear_token()

    client = RingClient(config=config)
    client.login(
        username=config.email,
        password=config.password,
        otp_callback=_read_otp_code,
    )

    # Clear legacy persisted OTP values from older auth flows.
    config._set("OTP_CODE", "")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="ring",
    login_handler=_login_handler,
)
