"""Authentication commands for LastPass CLI wrapper.

These commands delegate to the lpass CLI's authentication commands.
Uses create_auth_app from cli_tools_shared for standard auth infrastructure.
"""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config
from ..client import LastpassClient, ClientError


def _login_handler(config, force: bool):
    """Custom login handler for LastPass lpass CLI.

    Prompts for master password in Python and pipes it to lpass via stdin
    with LPASS_DISABLE_PINENTRY=1. This bypasses lpass's buggy pinentry
    code that causes malloc crashes on macOS.
    """
    import getpass
    client = LastpassClient(config=config)

    email = config.username
    if not email:
        raise ClientError("USERNAME is required. Run 'lastpass auth login --force' to configure it.")

    password = getpass.getpass("Master Password: ")

    from cli_tools_shared.output import print_info
    print_info(f"Logging in as: {email}")

    result = client.auth_login(email=email, password=password, force=force)

    if not result["success"]:
        raise ClientError(result.get("message", "Login failed"))


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="lastpass",
    login_handler=_login_handler,
)
