"""Main entry point for Asana CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="asana",
    help="CLI interface for Asana API",
    version=__version__,
)

# Register command modules
from .commands import auth, projects, tasks, custom_fields, users, workspaces, sections
app.add_typer(auth.app, name="auth", help="Manage Asana API authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")
register_commands(app, get_config, projects, name="projects", help="Manage Asana projects")
register_commands(app, get_config, tasks, name="tasks", help="Manage Asana tasks")
register_commands(app, get_config, custom_fields, name="custom-fields", help="Manage Asana custom fields")
register_commands(app, get_config, users, name="users", help="Manage Asana users")
register_commands(app, get_config, workspaces, name="workspaces", help="Manage Asana workspaces")
register_commands(app, get_config, sections, name="sections", help="Manage Asana sections")
def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
