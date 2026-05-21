"""Main entry point for Things CLI."""
import warnings

from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError

warnings.filterwarnings("ignore", module="urllib3")

app = create_app(
    name="things",
    help="CLI interface for Things 3 task management",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import todos, projects, areas, tags

app.add_typer(todos.app, name="todos", help="Manage todos")
app.add_typer(projects.app, name="projects", help="Manage projects")
app.add_typer(areas.app, name="areas", help="Manage areas")
app.add_typer(tags.app, name="tags", help="Manage tags")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
