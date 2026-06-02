"""Authentication commands for photos-app CLI.

For the Photos library, "authentication" is just checking if the library
is accessible (no credentials needed for local database access).
"""
from cli_tools_shared.auth_commands import create_auth_app

from ..config import get_config


def _test_handler(config):
    """Test Photos library accessibility."""
    return config.test_connection()


app = create_auth_app(get_config, tool_name="photos-app", test_handler=_test_handler)
