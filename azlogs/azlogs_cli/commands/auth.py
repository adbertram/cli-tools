"""Authentication commands for Azlogs CLI.

Delegates login to the upstream `az` CLI. Auth state is reported by
Config.test_connection() which probes `az account show`.
"""
from cli_tools_shared.auth_commands import create_auth_app

from ..config import get_config


def _login_handler(config, force: bool):
    """Delegate login to upstream `az` CLI."""
    import subprocess
    cmd = ["az", "login"]
    subprocess.run(cmd, check=True)


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="azlogs",
    login_handler=_login_handler,
)
