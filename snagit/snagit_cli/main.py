"""Main entry point for Snagit CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError

app = create_app(
    name="snagit",
    help="CLI for managing Snagit capture files (.snagx format)",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import capture
app.add_typer(capture.app, name="capture", help="Manage Snagit capture files")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
