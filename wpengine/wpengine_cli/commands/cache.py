"""WP Engine environment cache commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, print_json

from ..client import get_client
from ..config import get_config
from ._render import render_record

app = typer.Typer(help="Manage WP Engine environment caches", no_args_is_help=True)

CACHE_TYPES = {"object", "page", "cdn", "all"}


@app.command("clear")
@command
def cache_clear() -> None:
    """Remove cached CLI responses."""
    config = get_config()
    cache_dir = Path(config.storage_dir) / "cache"

    if not cache_dir.exists():
        print_json({"files_removed": 0, "bytes_freed": 0})
        return

    total_bytes = 0
    count = 0
    for cache_file in cache_dir.iterdir():
        if cache_file.is_file():
            total_bytes += cache_file.stat().st_size
            cache_file.unlink()
            count += 1

    print_json({"files_removed": count, "bytes_freed": total_bytes})


@app.command("purge")
@command
def cache_purge(
    environment_id: str = typer.Argument(..., help="WP Engine environment/install ID"),
    cache_type: str = typer.Option(
        "all",
        "--type",
        help="Cache type to purge: object, page, cdn, or all",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Purge object, page, CDN, or all caches for one environment."""
    normalized_type = cache_type.lower()
    if normalized_type not in CACHE_TYPES:
        raise ClientError("--type must be one of: object, page, cdn, all")
    result = get_client().purge_cache(environment_id, normalized_type)
    render_record(
        result,
        table=table,
        properties=properties,
        default_columns=["accepted", "environment_id", "type"],
    )


COMMAND_CREDENTIALS = {
    "purge": ["username_password"],
}
