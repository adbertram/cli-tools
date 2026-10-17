"""Auth commands for ATA Blog CLI."""
import typer

from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_info, print_success, print_error

from ..config import get_config, _active_profile_auth_status


def _login_handler(config, force):
    """Custom login handler that delegates to the notion CLI."""
    print_info("AtaBlog authenticates through the notion CLI:")
    print_info("  notion auth login")
    print_info("")

    notion_ok, notion_message = _active_profile_auth_status("notion")
    if notion_ok:
        print_success("Notion CLI already authenticated")
        return

    print_error(f"Notion CLI not authenticated: {notion_message}. Run: notion auth login")
    raise typer.Exit(1)


app = create_auth_app(get_config, tool_name="ata-blog", login_handler=_login_handler)
