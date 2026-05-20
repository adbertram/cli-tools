"""Media commands for WordPress CLI."""
import typer
from typing import Optional, List
from pathlib import Path
from mimetypes import guess_type

from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info
from ..filter_map import wordpress_filter_map
from . import model_to_dict, extract_fields, apply_client_side_filters


app = typer.Typer(help="Manage WordPress media library")

COMMAND_CREDENTIALS = {
    "delete": [
        "username_password"
    ],
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ],
    "upload": [
        "username_password"
    ]
}


def get_client():
    from ..client import get_client as _get_client
    return _get_client()


@app.command("list")
def media_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of media items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """List WordPress media items."""
    try:
        client = get_client()

        filters = wordpress_filter_map.to_api_params(filter) if filter else {}
        media_items = client.list_media(limit=limit, filters=filters)

        # Apply client-side filtering for fields without API translators
        media_items = apply_client_side_filters(media_items, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            media_items = extract_fields(media_items, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(media_items, fields, fields)
            else:
                print_table(
                    media_items,
                    ["id", "title", "source_url", "mime_type"],
                    ["ID", "Title", "URL", "MIME Type"],
                )
        else:
            print_json(media_items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def media_get(
    media_id: int = typer.Argument(..., help="The media ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """Get details for a specific WordPress media item."""
    try:
        client = get_client()
        media = client.get_media(media_id)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            media = extract_fields([media], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([media], fields, fields)
            else:
                media_dict = model_to_dict(media)
                rows = [{"field": k, "value": str(v)} for k, v in media_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(media)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("upload")
def media_upload(
    file_path: Path = typer.Argument(..., help="Path to the file to upload"),
):
    """Upload a local file to WordPress media library."""
    try:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {file_path}")

        print_info(f"Uploading file: {file_path.name}")

        file_data = file_path.read_bytes()
        file_size = len(file_data)
        print_info(f"File size: {file_size} bytes")

        content_type, _ = guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        print_info(f"Content type: {content_type}")

        client = get_client()
        media = client.upload_media(file_path.name, file_data, content_type)

        print_success(f"Media uploaded successfully (ID: {media.id})")
        print_info(f"URL: {media.source_url}")
        print_json(media)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def media_delete(
    media_id: int = typer.Argument(..., help="The media ID to delete"),
    force: bool = typer.Option(False, "--force", help="Permanently delete (skip trash)"),
):
    """Delete a media item from WordPress."""
    try:
        client = get_client()

        action = "Permanently deleting" if force else "Moving to trash"
        print_info(f"{action} media {media_id}")

        result = client.delete_media(media_id, force=force)

        if force:
            print_success(f"Media {media_id} permanently deleted")
        else:
            print_success(f"Media {media_id} moved to trash")

        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
