"""Main entry point for TwelveLabs CLI."""
import warnings

warnings.filterwarnings("ignore", module="urllib3")

from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="twelvelabs",
    help="CLI interface for TwelveLabs video AI API",
    version=__version__,
)

# Register command modules
from .commands import auth, indexes, videos, generate
app.add_typer(auth.app, name="auth", help="Manage TwelveLabs API authentication")
register_commands(app, get_config, indexes, name="indexes", help="Manage video indexes")
register_commands(app, get_config, videos, name="videos", help="Manage videos in indexes")
register_commands(app, get_config, generate, name="generate", help="Generate text from indexed videos")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
