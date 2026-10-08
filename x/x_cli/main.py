"""Main entry point for X CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_cache_config, get_config

app = create_app(
    name="x",
    help="CLI interface for X API",
    version=__version__,
)

# Register command modules
from .commands import analytics, auth, credits, tweet
app.add_typer(auth.app, name="auth", help="Manage X API authentication")
register_commands(
    app,
    get_config,
    credits,
    name="credits",
    help="Purchase X API credits",
)
register_commands(app, get_config, tweet, name="tweet", help="Manage tweets")
register_commands(app, get_config, analytics, name="analytics", help="Read post, audience, media, API usage and Ads analytics")
app.add_typer(create_cache_app(get_cache_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
