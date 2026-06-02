"""Authentication commands for Descript CLI."""
import typer

from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_error, print_info, print_success

from ..client import ClientError, DescriptClient
from ..config import get_config


def _login_handler(config, force: bool):
    """Extract and cache the Descript JWT from the running app."""
    if force:
        token_cache = config.get_profile_data_dir() / "token.json"
        if token_cache.exists():
            token_cache.unlink()
            print_info("Token cache cleared")

    try:
        DescriptClient(config=config)._get_jwt()
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)

    print_success("Successfully authenticated with Descript")
    print_info("Token is cached automatically. Run commands without re-authenticating.")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="descript",
    login_handler=_login_handler,
)
