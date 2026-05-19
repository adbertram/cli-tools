"""Main entry point for CcConnectSlackManager."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app

app = create_app(
    name="cc-connect-slack-manager",
    help="Manage the always-on Cody Slack cc-connect bridge",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import checks, config, service, slack_app, tokens

app.add_typer(checks.app, name="checks", help="Run Cody bridge health checks")
app.add_typer(config.app, name="config", help="Show Cody bridge configuration")
app.add_typer(service.app, name="service", help="Manage Cody bridge service")
app.add_typer(slack_app.app, name="app", help="Verify and test the Cody Slack app")
app.add_typer(tokens.app, name="tokens", help="Check Keychain token status")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
