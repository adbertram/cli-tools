"""Authentication commands for Descript CLI."""
import typer

from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_error

from ..config import get_config
from ..platform import PlatformCLIError, run_platform_passthrough


def _login_handler(config, force: bool):
    """Configure the official Descript API CLI API key."""
    try:
        code = run_platform_passthrough(["config", "set", "api-key"])
    except PlatformCLIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    raise typer.Exit(code)


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="descript",
    login_handler=_login_handler,
)
