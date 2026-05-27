"""Main entry point for Msword CLI."""

from cli_tools_shared import create_app, run_app

from . import __version__
from .commands import app as docs_app

app = create_app(name="msword", help="Read Word docs, convert to markdown, and extract comments with context", version=__version__, cache_support=False)

app.add_typer(docs_app, name="docs", help="Read, convert, and extract comments from Word documents")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
