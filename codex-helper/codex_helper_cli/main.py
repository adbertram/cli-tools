"""Main entry point for Codex Helper CLI."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.output import command, print_error, print_json, print_table

from . import __version__
from .client import get_client

app = create_app(
    name="codex-helper",
    help="Codex local app-server helper commands",
    version=__version__,
    cache_support=False,
)


def _limit_table_rows(usage: dict) -> list[dict]:
    rows = []
    for limit in usage["limits"]:
        for window_name in ("primary", "secondary"):
            window = limit[window_name]
            if window is None:
                continue
            rows.append(
                {
                    "limit_id": limit["limit_id"],
                    "window": window_name,
                    "used": window["used_percent"],
                    "left": window["left_percent"],
                    "duration_mins": window["window_duration_mins"],
                    "resets_at": window["resets_at_local"],
                }
            )
    return rows


@app.command("usage")
@command
def usage(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON output"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    timeout: int = typer.Option(30, "--timeout", help="Codex app-server timeout in seconds"),
):
    """Read Codex ChatGPT plan usage from the local Codex app-server."""
    if json_output and table:
        print_error("Use either --json or --table, not both.")
        raise typer.Exit(1)

    result = get_client().read_usage(timeout=timeout)
    if table:
        rows = _limit_table_rows(result)
        print_table(
            rows,
            ["limit_id", "window", "used", "left", "duration_mins", "resets_at"],
            ["Limit", "Window", "Used %", "Left %", "Mins", "Resets At"],
        )
        return
    print_json(result)


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
