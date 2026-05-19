"""Main entry point for Kick CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="kick",
    help="CLI interface for Kick API",
    version=__version__,
)

# Register command modules
from .commands import auth, transactions, categories, workspaces, entities, statistics, rule_groups, clients, integrations
app.add_typer(auth.app, name="auth", help="Manage Kick API authentication")
register_commands(app, get_config, transactions, name="transactions", help="Manage Kick transactions")
register_commands(app, get_config, categories, name="categories", help="Manage Kick categories")
register_commands(app, get_config, workspaces, name="workspaces", help="Manage Kick workspaces")
register_commands(app, get_config, entities, name="entities", help="Manage Kick entities")
register_commands(app, get_config, statistics, name="statistics", help="Get Kick transaction statistics")
register_commands(app, get_config, rule_groups, name="rule-groups", help="Manage Kick rule groups")
register_commands(app, get_config, clients, name="clients", help="Manage Kick clients")
register_commands(app, get_config, integrations, name="integrations", help="Manage Kick integrations")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
