"""Authentication commands for Grammarly CLI."""
import typer
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_error, print_success

from ..config import get_config


def _login_handler(config, force: bool):
    """Validate OAuth client credentials and save an access token."""
    from ..client import ClientError, GrammarlyClient

    try:
        GrammarlyClient(config=config).obtain_access_token()
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(2)

    print_success("OAuth credentials validated and access token saved")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="grammarly",
    login_handler=_login_handler,
)
