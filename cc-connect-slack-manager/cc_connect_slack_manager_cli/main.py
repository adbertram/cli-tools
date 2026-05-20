"""Main entry point for CcConnectSlackManager."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, create_auth_app, run_app
from cli_tools_shared.command_registry import register_commands
from .config import get_config

app = create_app(
    name="cc-connect-slack-manager",
    help="Manage the always-on Cody Slack cc-connect bridge",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import app as slack_app, checks, config, service, tokens

app.add_typer(
    create_auth_app(get_config, tool_name="cc-connect-slack-manager"),
    name="auth",
    help="Manage local bridge authentication",
)
register_commands(app, get_config, checks, name="checks", help="Run Cody bridge health checks")
register_commands(app, get_config, config, name="config", help="Show Cody bridge configuration")
register_commands(app, get_config, service, name="service", help="Manage Cody bridge service")
register_commands(app, get_config, slack_app, name="app", help="Verify and test the Cody Slack app")
register_commands(app, get_config, tokens, name="tokens", help="Check Keychain token status")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
