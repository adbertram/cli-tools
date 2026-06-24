"""Main entry point for Google CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="google",
    help="CLI interface for Google Workspace APIs",
    version=__version__,
)

# Register command modules
from .commands import analytics, auth, calendar, chat, cloud, contacts, docs, drive, gmail, lookerstudio, searchconsole, sheets, webstore

app.add_typer(auth.app, name="auth", help="Manage authentication")
register_commands(app, get_config, analytics, name="analytics", help="Access Google Analytics data")
register_commands(app, get_config, calendar, name="calendar", help="Access Google Calendar events")
register_commands(app, get_config, chat, name="chat", help="Access Google Chat messages")
register_commands(app, get_config, cloud, name="cloud", help="Manage Google Cloud resources")
register_commands(app, get_config, contacts, name="contacts", help="Access Google Contacts")
register_commands(app, get_config, docs, name="docs", help="Manage Google Docs documents")
register_commands(app, get_config, drive, name="drive", help="Manage Google Drive files")
register_commands(app, get_config, gmail, name="gmail", help="Access Gmail messages")
register_commands(app, get_config, lookerstudio, name="lookerstudio", help="Manage Looker Studio assets")
register_commands(app, get_config, searchconsole, name="searchconsole", help="Access Google Search Console")
register_commands(app, get_config, sheets, name="sheets", help="Manage Google Sheets spreadsheets")
register_commands(app, get_config, webstore, name="webstore", help="Manage Chrome Web Store items")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage response cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
