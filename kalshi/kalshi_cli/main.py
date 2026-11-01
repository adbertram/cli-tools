"""Main entry point for Kalshi CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .config import Config, get_config, login_handler

app = create_app(name="kalshi", help="Kalshi prediction-market CLI: live market data, orders, balance and positions", version=__version__)

from .commands import balance, markets, metrics, orders, positions, presets, stream  # noqa: E402


def get_public_config(profile=None):
    """Public groups never touch credentials, so they must not pay for loading the profile secrets."""
    return None


get_public_config.config_cls = Config

register_commands(app, get_public_config, presets, name="presets", help="Market presets (name to series ticker)")
register_commands(app, get_public_config, markets, name="markets", help="Read markets and the current open market of a series")
register_commands(app, get_public_config, metrics, name="metrics", help="Measure request latency")
register_commands(app, get_config, stream, name="stream", help="Stream live market data over WebSocket")
register_commands(app, get_config, orders, name="orders", help="List, place and cancel orders")
register_commands(app, get_config, balance, name="balance", help="Account balance and portfolio value")
register_commands(app, get_config, positions, name="positions", help="List and inspect positions")

app.add_typer(create_auth_app(get_config, tool_name="kalshi", login_handler=login_handler), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
