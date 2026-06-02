"""Authentication commands for Monarch CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config
from ..client import MonarchClient, ClientError


def _login_handler(config, force: bool):
    """Custom login handler for Monarch Money email/password/MFA flow.

    MFA handling priority:
    1. MFA_SECRET in .env as TOTP secret (base32) -> auto-generates codes
    2. MFA_SECRET in .env as one-time code (numeric) -> uses directly
    3. Interactive prompt for MFA code (if neither above is available)
    """
    client = MonarchClient(config=config)

    if force:
        config.clear_session()

    # First login attempt uses MFA_SECRET from config (TOTP secret or one-time code)
    result = client.login(
        email=config.username,
        password=config.password,
        mfa_code=None,
    )

    if result.get("mfa_required"):
        raise ClientError(
            "MFA is required. Set MFA_SECRET to a TOTP secret or one-time code "
            "and rerun 'monarch auth login'."
        )

    if not result["success"]:
        raise ClientError(result.get("message", "Login failed"))


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="monarch",
    login_handler=_login_handler,
)
