"""Authentication commands for ShopGoodwill CLI."""
import typer
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_error, print_success

from ..config import get_config


def _login_handler(config, force: bool):
    """Validate ShopGoodwill credentials and save the access token."""
    from ..client import ClientError, ShopGoodwillClient

    try:
        result = ShopGoodwillClient(require_auth=False, config=config).login(
            config.username,
            config.password,
        )
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(2)

    access_token = result.get("accessToken")
    if not access_token:
        print_error("Authentication succeeded but no access token was returned")
        raise typer.Exit(1)

    config.save_access_token(access_token)
    print_success(f"Authenticated as {config.username}")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="shopgoodwill",
    login_handler=_login_handler,
)
