"""Main entry point for ATA Blog CLI wrapper."""
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
from .commands import auth, notion_page, wordpress_post, wordpress_page, wordpress_admin, media, categories, tags, raptive, schema, earnings, shoutouts

app.add_typer(auth.app, name="auth", help="Manage ata-blog authentication")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, notion_page, name="notion-page", help="Manage Notion pages")
register_commands(app, get_config, wordpress_post, name="wordpress-post", help="Manage WordPress posts")
register_commands(app, get_config, wordpress_page, name="wordpress-page", help="Manage WordPress pages")
register_commands(app, get_config, wordpress_admin, name="wordpress-admin", help="Manage WordPress admin operations")
register_commands(app, get_config, media, name="media", help="Manage WordPress media")
register_commands(app, get_config, categories, name="categories", help="Manage WordPress categories")
register_commands(app, get_config, tags, name="tags", help="Manage WordPress tags")
register_commands(app, get_config, raptive, name="raptive", help="Manage Raptive (AdThrive) ad settings")
register_commands(app, get_config, schema, name="schema", help="Manage Rank Math schema markup")
register_commands(app, get_config, earnings, name="earnings", help="Query ad earnings and revenue data")
register_commands(app, get_config, shoutouts, name="shoutouts", help="Manage sponsored shoutouts in posts")
def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
