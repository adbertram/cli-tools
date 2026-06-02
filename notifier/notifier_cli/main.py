"""Main entry point for Notifier CLI wrapper."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app

app = create_app(name="notifier", help="CLI wrapper for terminal-notifier - macOS desktop notifications", version=__version__, cache_support=False)

# Register command modules
from . import commands

# Add send command at top level
app.command("send")(commands.send_notification)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
