"""Shared command-level validation helpers."""

import typer
from cli_tools_shared.output import print_error


def usage_error(message: str) -> None:
    """Print a CLI usage error and exit with Click's conventional code."""
    print_error(message)
    raise typer.Exit(2)
