"""Main entry point for Wordpress CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError

app = create_app(
    name="wordpress",
    help="CLI interface for Wordpress API",
    version=__version__,
)

from .config import get_config

# Register auth commands using cli_tools_shared
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.command_registry import register_commands
auth_app = create_auth_app(get_config, tool_name="wordpress")

app.add_typer(auth_app, name="auth", help="Manage WordPress API authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")

# Register command modules
from .commands import posts, pages, media, categories, tags, admin, org, menus
register_commands(app, get_config, posts, name="posts", help="Manage WordPress posts")
register_commands(app, get_config, pages, name="pages", help="Manage WordPress pages")
register_commands(app, get_config, media, name="media", help="Manage WordPress media library")
register_commands(app, get_config, categories, name="categories", help="Manage WordPress categories")
register_commands(app, get_config, tags, name="tags", help="Manage WordPress tags")
register_commands(app, get_config, menus, name="menus", help="Manage WordPress navigation menus")
register_commands(app, get_config, admin, name="admin", help="WordPress admin commands")
register_commands(app, get_config, org, name="org", help="Manage WordPress.com organization access")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
