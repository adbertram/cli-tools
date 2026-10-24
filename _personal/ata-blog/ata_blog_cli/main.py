"""Main entry point for ATA Blog CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config


app = create_app(
    name="ata-blog",
    help="CLI for managing ATA Blog (adamtheautomator.com)",
    version=__version__,
)

# Register command modules
from .commands import auth, notion_page, media, categories, tags, earnings

app.add_typer(auth.app, name="auth", help="Manage ata-blog authentication")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, notion_page, name="notion-page", help="Manage Notion pages")
register_commands(app, get_config, media, name="media", help="Upload media to the static site")
register_commands(app, get_config, categories, name="categories", help="Manage static site categories")
register_commands(app, get_config, tags, name="tags", help="Manage static site tags")
register_commands(app, get_config, earnings, name="earnings", help="Query ad earnings and revenue data")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
