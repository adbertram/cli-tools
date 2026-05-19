"""Authentication commands for Ring CLI.

This CLI uses the auth contract exposed by ``python-ring-doorbell``:
``Auth.async_fetch_token(username, password, otp_code=None)``. It does not use
Ring Partner API client credentials or hosted OAuth/account-linking endpoints.

The shared ``create_auth_app`` from ``cli_tools_shared`` handles prompting for
``USERNAME``, ``PASSWORD``, and the Ring 2FA code via ``AUTH_EXTRA_PROMPTS``,
then delegates token acquisition to ``_login_handler``.
"""
from cli_tools_shared.auth_commands import create_auth_app

from ..client import RingClient
from ..config import get_config


def _login_handler(config, force: bool):
    """Custom login handler for ring-doorbell's consumer OAuth + 2FA flow.

    ``create_auth_app`` has already prompted for USERNAME, PASSWORD and
    OTP_CODE via ``AUTH_EXTRA_PROMPTS``. We exchange them for an OAuth
    token via the ring-doorbell SDK and persist it in the profile data
    directory. The OTP code is cleared after a successful exchange so a
    stale code is never reused.
    """
    if force:
        config.clear_token()

    otp_code = config._get("OTP_CODE")

    client = RingClient(config=config)
    client.login(
        username=config.email,
        password=config.password,
        otp_callback=lambda: otp_code,
    )

    # OTP codes are single-use — never persist them across runs.
    config._set("OTP_CODE", "")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="ring",
    login_handler=_login_handler,
)
