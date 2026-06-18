"""Main entry point for CVS CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app

app = create_app(name="cvs", help="CLI interface for CVS pharmacy API", version=__version__)

# Register command modules
from cli_tools_shared.command_registry import register_commands
from .commands import auto_refills, prescriptions, orders, refills
register_commands(app, get_config, auto_refills, name="auto-refills", help="Start or stop auto-refill")
register_commands(app, get_config, prescriptions, name="prescriptions", help="Manage prescriptions")
register_commands(app, get_config, orders, name="orders", help="Manage orders")
register_commands(app, get_config, refills, name="refills", help="Check refill eligibility")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="cvs"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
