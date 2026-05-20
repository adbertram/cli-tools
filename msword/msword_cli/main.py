"""Main entry point for Msword CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.exceptions import ClientError

from . import __version__
from .commands import app as docs_app
from .config import get_config

app = create_app(name="msword", help="Read Word docs, convert to markdown, and extract comments with context", version=__version__, cache_support=False)

app.add_typer(docs_app, name="docs", help="Read, convert, and extract comments from Word documents")
app.add_typer(create_auth_app(get_config, tool_name="msword"), name="auth")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
