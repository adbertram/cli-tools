"""Authentication commands for Instacart CLI."""
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_info, print_success

from ..config import get_config


def _login_handler(config, force: bool):
    """Show the required browser-session capture workflow."""
    if force:
        config.clear_credentials()
        print_info("Existing session cleared")

    if config.has_credentials() and not config.is_session_expired():
        print_success("Already authenticated. Use --force to re-authenticate.")
        return

    print_info(
        "Browser session authentication required.\n\n"
        "To authenticate:\n"
        "1. Open https://www.instacart.com in your browser\n"
        "2. Log in to your account\n"
        "3. Capture cookies after login\n"
        f"4. Save session JSON to {config.session_path}"
    )


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="instacart",
    login_handler=_login_handler,
)
