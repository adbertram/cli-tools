"""Main entry point for iMessage CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError

app = create_app(
    name="imessage",
    help="CLI for iMessage on macOS",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import contacts, conversations, messages
app.add_typer(contacts.app, name="contacts", help="Manage contacts")
app.add_typer(conversations.app, name="conversations", help="Manage conversations")
app.add_typer(messages.app, name="messages", help="Manage messages")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
