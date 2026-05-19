"""Authentication commands for Airtable CLI."""
from cli_tools_shared.auth_commands import create_auth_app

from ..config import get_config

app = create_auth_app(get_config, tool_name="airtable")
