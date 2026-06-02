"""Authentication commands for Notion CLI."""
from cli_tools_shared.auth_commands import create_auth_app

from ..config import get_config


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="notion",
)
