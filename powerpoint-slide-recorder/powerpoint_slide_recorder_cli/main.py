"""Main entry point for powerpoint-slide-recorder."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app

app = create_app(
    name="powerpoint-slide-recorder",
    help="Record narrated PowerPoint slides",
    version=__version__,
    cache_support=False,
)

from .commands import record

app.command("record")(record)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
