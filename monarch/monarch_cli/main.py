"""Main entry point for Monarch CLI."""
# Suppress warnings before any library imports
import warnings
warnings.filterwarnings("ignore", module="urllib3")
# Suppress gql SSL certificate warning (AIOHTTPTransport)
warnings.filterwarnings(
    "ignore",
    message=".*AIOHTTPTransport does not verify ssl certificates.*",
    category=UserWarning,
    module="gql.transport.aiohttp"
)

from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="monarch", help="CLI for Monarch Money personal finance", version=__version__)

# Register command modules
from .commands import auth, accounts, transactions, budgets, categories, category_groups, tags, cashflow, institutions, merchants, rules
from .config import get_config

app.add_typer(auth.app, name="auth", help="Manage authentication")
register_commands(app, get_config, accounts, name="accounts", help="Manage accounts")
register_commands(app, get_config, transactions, name="transactions", help="Manage transactions")
register_commands(app, get_config, budgets, name="budgets", help="View budgets")
register_commands(app, get_config, categories, name="categories", help="Manage categories")
register_commands(app, get_config, category_groups, name="category-groups", help="Manage category groups")
register_commands(app, get_config, tags, name="tags", help="Manage tags")
register_commands(app, get_config, cashflow, name="cashflow", help="View cashflow")
register_commands(app, get_config, institutions, name="institutions", help="Manage linked institutions")
register_commands(app, get_config, merchants, name="merchants", help="Manage merchants")
register_commands(app, get_config, rules, name="rules", help="Manage transaction rules")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
