import warnings

warnings.filterwarnings("ignore", module="urllib3")

from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="impact", help="Impact.com Publisher API CLI", version=__version__)

from .commands import account, actions, ads, campaigns, catalogs, clicks, jobs, marketplace, reports, websites

register_commands(app, get_config, account, name="account", help="Manage account data", cli_name="impact")
register_commands(app, get_config, campaigns, name="campaigns", help="Manage programs and program assets", cli_name="impact")
register_commands(app, get_config, ads, name="ads", help="Manage ads", cli_name="impact")
register_commands(app, get_config, actions, name="actions", help="Manage actions", cli_name="impact")
register_commands(app, get_config, catalogs, name="catalogs", help="Manage catalogs", cli_name="impact")
register_commands(app, get_config, reports, name="reports", help="Run and export reports", cli_name="impact")
register_commands(app, get_config, clicks, name="clicks", help="Retrieve and export clicks", cli_name="impact")
register_commands(app, get_config, jobs, name="jobs", help="Manage async jobs", cli_name="impact")
register_commands(app, get_config, websites, name="websites", help="Manage websites", cli_name="impact")
register_commands(
    app,
    get_config,
    marketplace,
    name="marketplace",
    help="Generate browser-automation instructions for Impact marketplace discovery (no public API)",
    cli_name="impact",
)

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="impact"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
