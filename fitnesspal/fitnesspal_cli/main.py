"""Main entry point for MyFitnessPal CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from .config import get_config

app = create_app(
    name="fitnesspal",
    help="MyFitnessPal CLI - View diary, exercises, measurements, reports, and food data",
    version=__version__,
)

# Register command modules
from .commands import diary, exercises, measurements, reports, food, recipes, meals

register_commands(app, get_config, diary, name="diary", help="View food diary entries")
register_commands(app, get_config, exercises, name="exercises", help="View exercise entries")
register_commands(app, get_config, measurements, name="measurements", help="View body measurements")
register_commands(app, get_config, reports, name="reports", help="View nutrition and fitness reports")
register_commands(app, get_config, food, name="food", help="Search and view food items")
register_commands(app, get_config, recipes, name="recipes", help="View saved recipes")
register_commands(app, get_config, meals, name="meals", help="View saved meals")

# Register shared auth + cache apps
app.add_typer(create_auth_app(get_config, tool_name="fitnesspal"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
