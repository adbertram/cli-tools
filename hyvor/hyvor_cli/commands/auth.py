"""Authentication commands for Hyvor CLI - uses cli_tools_shared."""
from cli_tools_shared import create_auth_app
from ..config import get_config

app = create_auth_app(get_config, tool_name="hyvor")
