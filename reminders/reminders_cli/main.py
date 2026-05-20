"""Main entry point for Reminders CLI."""

from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError

app = create_app(
    name="reminders",
    help="CLI for managing macOS Reminders",
    version=__version__,
    cache_support=False,
)

from .commands import lists, reminders

app.add_typer(lists.app, name="lists", help="Manage reminder lists")
app.command("list")(reminders.list_reminders)
app.command("show")(reminders.show_reminder)
app.command("create")(reminders.create_reminder)
app.command("complete")(reminders.complete_reminder)
app.command("uncomplete")(reminders.uncomplete_reminder)
app.command("delete")(reminders.delete_reminder)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
