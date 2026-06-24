"""Main entry point for Descript CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands, register_root_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="descript",
    help="CLI interface for Descript API",
    version=__version__,
)

# Register command modules
from .commands import api, auth, compositions, config, monitor, projects
from cli_tools_shared.cache_commands import create_cache_app
app.add_typer(auth.app, name="auth", help="Manage Descript authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")
register_commands(app, get_config, config, name="config", help="Manage official Descript API CLI configuration")
register_commands(app, get_config, compositions, name="compositions", help="Manage project compositions")
register_commands(app, get_config, monitor, name="monitor", help="Monitor Descript network activity")
register_commands(app, get_config, projects, name="projects", help="Manage Descript projects")
register_root_commands(app, get_config, api)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
