"""Authentication commands for Dropbox CLI.

Dropbox uses OAuth with app_key/app_secret (mapped to CLIENT_ID/CLIENT_SECRET)
and refresh tokens. The built-in auth commands from cli-tools-shared handle
the standard login/logout/status/test flow with --profile support.
"""

from cli_tools_shared.auth_commands import create_auth_app

from ..config import get_config

# Auth app with login, logout, status, refresh, and test commands.
# test_connection() on Config drives the 'test' command automatically.
app = create_auth_app(get_config, tool_name="dropbox")
