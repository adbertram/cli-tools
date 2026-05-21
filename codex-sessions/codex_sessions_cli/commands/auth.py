"""Authentication commands backed by the shared auth app."""

from cli_tools_shared import create_auth_app

from ..config import get_config

app = create_auth_app(get_config, tool_name="codex-sessions")
