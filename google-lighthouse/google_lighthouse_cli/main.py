"""Main entry point for the Google Lighthouse CLI wrapper."""

from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app

app = create_app(
    name="google-lighthouse",
    help="Run and manage Google Lighthouse audits",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import audits

app.add_typer(audits.app, name="audits", help="Manage Lighthouse audits")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
