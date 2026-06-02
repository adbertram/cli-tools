"""Main entry point for Mailchimp CLI."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="mailchimp", help="CLI interface for Mailchimp API", version=__version__)

# Register command modules
from .commands import auth, audiences, forms, members, campaigns, templates
from .config import get_config

app.add_typer(auth.app, name="auth", help="Manage Mailchimp API authentication")
register_commands(app, get_config, audiences, name="audiences", help="Manage Mailchimp audiences/lists")
register_commands(app, get_config, forms, name="forms", help="Manage list signup forms")
register_commands(app, get_config, members, name="members", help="Manage list members/subscribers")
register_commands(app, get_config, campaigns, name="campaigns", help="Manage email campaigns")
register_commands(app, get_config, templates, name="templates", help="Manage email templates")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
