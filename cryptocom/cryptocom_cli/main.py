"""Main entry point for Crypto.com Exchange CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="cryptocom", help="Crypto.com Exchange API CLI", version=__version__)

# Register command modules
from .commands import account, book, candlesticks, instruments, ticker, trades

register_commands(app, get_config, account, name="account", help="Inspect authenticated account data")
register_commands(app, get_config, book, name="book", help="Inspect order books")
register_commands(app, get_config, candlesticks, name="candlesticks", help="Inspect candlesticks")
register_commands(app, get_config, instruments, name="instruments", help="Inspect Exchange instruments")
register_commands(app, get_config, ticker, name="ticker", help="Inspect ticker data")
register_commands(app, get_config, trades, name="trades", help="Inspect public trades")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="cryptocom"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
