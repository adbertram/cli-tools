"""Main entry point for the 10Web CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="tenweb", help="CLI interface for the 10Web API", version=__version__)

# Register command modules
from .commands import subdomains, websites
register_commands(app, get_config, websites, name="websites", help="Manage 10Web websites")
register_commands(app, get_config, subdomains, name="subdomains", help="Check 10Web subdomain availability")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="tenweb"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
