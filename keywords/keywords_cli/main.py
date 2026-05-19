"""Main entry point for Keywords CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from .client import ClientError
from .config import get_config

app = create_app(
    name="keywords",
    help="Query autocomplete suggestions from search engines for keyword research",
    version=__version__,
)

# Register command modules
from .commands import suggest

app.add_typer(suggest.app, name="suggest", help="Query autocomplete suggestions")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
