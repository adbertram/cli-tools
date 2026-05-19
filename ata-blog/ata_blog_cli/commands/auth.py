"""Auth commands for ATA Blog CLI."""
import subprocess

from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_info, print_success, print_error

from ..config import get_config


def _login_handler(config, force):
    """Custom login handler that delegates to underlying CLIs."""
    print_info("AtaBlog wraps two CLIs. Authenticate each:")
    print_info("  wordpress auth login")
    print_info("  notion auth login")
    print_info("")

    wp = subprocess.run(
        ["wordpress", "auth", "status"],
        capture_output=True, text=True, timeout=10,
    )
    notion = subprocess.run(
        ["notion", "auth", "status"],
        capture_output=True, text=True, timeout=10,
    )

    if wp.returncode == 0 and notion.returncode == 0:
        print_success("Both CLIs already authenticated")
    else:
        if wp.returncode != 0:
            print_error("WordPress CLI not authenticated. Run: wordpress auth login")
        if notion.returncode != 0:
            print_error("Notion CLI not authenticated. Run: notion auth login")


app = create_auth_app(get_config, tool_name="ata-blog", login_handler=_login_handler)
