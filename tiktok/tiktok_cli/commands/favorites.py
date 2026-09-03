"""Favorites (saved/bookmarked TikTok videos) commands for TikTok CLI.

``list`` needs a logged-in TikTok session (see ``FavoritesClient`` in
``client.py`` for why); ``get`` looks up one video's details by id or URL via
the existing yt-dlp-backed client, which needs no login.
"""
COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["custom"],
}

from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import ClientError, command, print_json, print_table

from ..client import (
    favorite_from_video_metadata,
    favorite_id_to_url,
    get_client,
    get_favorites_client,
)

app = typer.Typer(help="Manage saved (favorited) TikTok videos")

_COLUMNS = ["id", "url", "caption", "author", "saved_at"]


@app.command("list")
@command
def list_favorites(
    table: bool = typer.Option(False, "--table", "-t", help="Display results as a table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., author:eq:someuser)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """List all of the logged-in account's saved (favorited) TikTok videos."""
    if filter:
        try:
            validate_filters(filter)
        except FilterValidationError as e:
            raise ClientError(str(e)) from e

    favorites = get_favorites_client().list_favorites(limit=limit)

    if filter:
        favorites = apply_filters(favorites, filter)
    if properties:
        favorites = apply_properties_filter(favorites, properties)

    if table:
        columns = [p.strip() for p in properties.split(",")] if properties else _COLUMNS
        print_table(favorites, columns, columns)
    else:
        print_json(favorites)


@app.command("get")
@command
def get_favorite(
    item: str = typer.Argument(..., help="Video id or tiktok.com video URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as a table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """Get one saved video's details by id or URL."""
    url = favorite_id_to_url(item)
    metadata = get_client().get_video_metadata(url)
    favorite = favorite_from_video_metadata(metadata)

    if properties:
        favorite = apply_properties_filter([favorite], properties)[0]

    if table:
        columns = [p.strip() for p in properties.split(",")] if properties else _COLUMNS
        print_table([favorite], columns, columns)
    else:
        print_json(favorite)
