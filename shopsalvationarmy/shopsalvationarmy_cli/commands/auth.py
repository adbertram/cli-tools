"""Authentication commands for ShopSalvationArmy CLI."""
import typer
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import print_error, print_success

from ..config import get_config


def _login_handler(config, force: bool):
    """Validate Shop Salvation Army credentials."""
    from ..client import ClientError, ShopSalvationArmyClient

    try:
        result = ShopSalvationArmyClient(require_auth=False, config=config).login(
            config.username,
            config.password,
        )
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(2)

    if not result.get("authenticated"):
        print_error("Authentication failed")
        raise typer.Exit(1)

    print_success(f"Authenticated as {config.username}")


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="shopsalvationarmy",
    login_handler=_login_handler,
)
