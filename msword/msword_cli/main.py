"""Main entry point for Msword CLI."""
from . import __version__
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared import create_app, run_app

app = create_app(name="msword", help="Read Word docs, convert to markdown, and extract comments with context", version=__version__, cache_support=False)

# Register command modules
from .commands import items
app.add_typer(items.app, name="docs", help="Read, convert, and extract comments from Word documents")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
