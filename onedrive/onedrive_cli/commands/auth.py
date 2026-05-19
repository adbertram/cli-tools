"""Authentication commands for OneDrive CLI using create_auth_app."""
from cli_tools_shared.auth_commands import create_auth_app
from ..config import get_config
from ..msal_auth import login_handler, test_handler

app = create_auth_app(
    get_config_fn=get_config,
    tool_name="onedrive",
    login_handler=login_handler,
    test_handler=test_handler,
)
