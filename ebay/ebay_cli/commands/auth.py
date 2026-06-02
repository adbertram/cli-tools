"""Authentication commands for eBay CLI.

eBay uses OAuth 2.0 with authorization code grant flow. The built-in
oauth_login handler from cli-tools-shared handles the full flow:
browser authorization, code capture, and token exchange.
"""

from cli_tools_shared.auth_commands import create_auth_app

from ..config import get_config
from . import profiles

# Auth app with login, logout, status, and refresh commands.
# No custom login_handler needed — OAUTH_* class vars on Config drive
# the built-in oauth_login handler automatically.
app = create_auth_app(get_config, tool_name="ebay", profiles_app=profiles.app)
