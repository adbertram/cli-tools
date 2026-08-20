"""Authentication commands backed by the shared auth app.

deepseek-sessions reads local files under the dsh home. There is no remote
credential; `auth status` reports whether that store is readable.
"""
from cli_tools_shared import create_auth_app

from ..config import get_config

app = create_auth_app(get_config, tool_name="deepseek-sessions")
