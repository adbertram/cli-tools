"""Bookmark management commands for Slack CLI."""

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}

import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError, apply_properties_filter

app = typer.Typer(help="Manage Slack channel bookmarks")


@app.command("list")
def list_bookmarks(
    channel_id: str = typer.Argument(..., help="Channel ID to list bookmarks for"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of bookmarks"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List bookmarks in a channel.

    Example:
        slack bookmarks list C1234567890
        slack bookmarks list C1234567890 --table
    """
    try:
        client = get_client()
        response = client.list_bookmarks(channel_id)
        bookmarks = response.get("bookmarks", [])

        # Apply client-side filters
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                raise typer.BadParameter(str(e))
            bookmarks = apply_filters(bookmarks, filter_)

        # Apply limit
        bookmarks = bookmarks[:limit]

        if properties:
            bookmarks = apply_properties_filter(bookmarks, properties)

        if table:
            from datetime import datetime

            table_data = [
                {
                    "id": b.get("id"),
                    "title": b.get("title", ""),
                    "type": b.get("type", ""),
                    "link": b.get("link", "")[:50] + "..." if len(b.get("link", "")) > 50 else b.get("link", ""),
                    "emoji": b.get("emoji", ""),
                    "created": datetime.fromtimestamp(b.get("date_created", 0)).strftime("%Y-%m-%d")
                    if b.get("date_created")
                    else "",
                }
                for b in bookmarks
            ]
            print_table(
                table_data,
                ["id", "title", "type", "link", "emoji", "created"],
                ["ID", "Title", "Type", "Link", "Emoji", "Created"],
            )
        else:
            print_json({"bookmarks": bookmarks, "count": len(bookmarks)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_bookmark(
    channel_id: str = typer.Argument(..., help="Channel ID where bookmark exists"),
    bookmark_id: str = typer.Argument(..., help="Bookmark ID to get"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific bookmark by ID.

    Example:
        slack bookmarks get C1234567890 Bk123ABC4DEF
        slack bookmarks get C1234567890 Bk123ABC4DEF --table
    """
    try:
        client = get_client()
        response = client.list_bookmarks(channel_id)
        bookmarks = response.get("bookmarks", [])

        # Find the specific bookmark
        bookmark = None
        for b in bookmarks:
            if b.get("id") == bookmark_id:
                bookmark = b
                break

        if not bookmark:
            typer.echo(f"Bookmark {bookmark_id} not found in channel {channel_id}", err=True)
            raise typer.Exit(1)

        if table:
            from datetime import datetime

            table_data = [
                {
                    "id": bookmark.get("id"),
                    "title": bookmark.get("title", ""),
                    "type": bookmark.get("type", ""),
                    "link": bookmark.get("link", ""),
                    "emoji": bookmark.get("emoji", ""),
                    "icon_url": bookmark.get("icon_url", ""),
                    "created": datetime.fromtimestamp(bookmark.get("date_created", 0)).strftime("%Y-%m-%d %H:%M")
                    if bookmark.get("date_created")
                    else "",
                    "updated": datetime.fromtimestamp(bookmark.get("date_updated", 0)).strftime("%Y-%m-%d %H:%M")
                    if bookmark.get("date_updated")
                    else "",
                    "created_by": bookmark.get("last_updated_by_user_id", ""),
                }
            ]
            print_table(
                table_data,
                ["id", "title", "type", "link", "emoji", "created", "updated", "created_by"],
                ["ID", "Title", "Type", "Link", "Emoji", "Created", "Updated", "Created By"],
            )
        else:
            print_json(bookmark)

    except Exception as e:
        raise typer.Exit(handle_error(e))
