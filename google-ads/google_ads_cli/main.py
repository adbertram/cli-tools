"""Entry point for complete Google Ads API CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from . import __version__
from .config import get_config
from .schema import DEFAULT_API_VERSION, SDK_VERSION
from .commands import api, customers, query
from .commands.auth import app as auth_app

app = create_app(name="google-ads", help=f"Complete Google Ads API gateway (SDK{SDK_VERSION}; default API{DEFAULT_API_VERSION}).", version=__version__)
register_commands(app, get_config, api, name="api", help="Offline discovery and full RPC access.")
register_commands(app, get_config, query, name="query", help="GAQL reporting.")
register_commands(app, get_config, customers, name="customers", help="Accessible customer accounts.")
app.add_typer(auth_app, name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    run_app(app)


if __name__ == "__main__":
    main()
