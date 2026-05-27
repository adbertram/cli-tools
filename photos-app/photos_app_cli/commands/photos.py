"""Photos commands for listing and downloading photos."""
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import typer

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_error, print_success, print_info, print_table
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

COMMAND_CREDENTIALS = {
    "count": [
        "custom"
    ],
    "download": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}

app = typer.Typer(help="Photo operations")


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string in YYYY-MM-DD format."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise typer.BadParameter(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")


@app.command("list")
def list_photos(
    from_date: Optional[str] = typer.Option(
        None, "--from", help="Start date (YYYY-MM-DD)"
    ),
    to_date: Optional[str] = typer.Option(
        None, "--to", "-t", help="End date (YYYY-MM-DD)"
    ),
    album: Optional[str] = typer.Option(
        None, "--album", "-a", help="Filter by album name"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Max results"),
    include_videos: bool = typer.Option(
        False, "--videos", "-v", help="Include videos"
    ),
    include_hidden: bool = typer.Option(
        False, "--hidden", help="Include hidden photos"
    ),
    table: bool = typer.Option(False, "--table", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List photos from the Photos library.

    By default returns JSON with photo metadata. Use --table for tabular output.

    Examples:
        photos-app photos list --limit 10
        photos-app photos list --from 2024-01-01 --to 2024-12-31
        photos-app photos list --album "Vacation 2024"
        photos-app photos list --table
        photos-app photos list --filter "is_favorite:eq:true"
        photos-app photos list --properties uuid,filename,date_created
    """
    try:
        # Validate filters if provided
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                print_error(f"Invalid filter: {e}")
                raise typer.Exit(1)

        client = get_client()

        from_dt = parse_date(from_date)
        to_dt = parse_date(to_date)

        photos = client.list_photos(
            from_date=from_dt,
            to_date=to_dt,
            limit=limit,
            include_hidden=include_hidden,
            include_videos=include_videos,
            album=album,
        )

        if not photos:
            print_info("No photos found matching criteria")
            if not table:
                print_json([])
            return

        # Convert to dictionaries
        photos_data = [p.to_dict() for p in photos]

        # Apply client-side filtering
        if filter:
            photos_data = apply_filters(photos_data, filter)

        if not photos_data:
            print_info("No photos match the filters")
            if not table:
                print_json([])
            return

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            photos_data = [{k: v for k, v in photo.items() if k in prop_list} for photo in photos_data]

        # Output
        if table:
            if properties:
                headers = [p.strip().replace("_", " ").title() for p in properties.split(",")]
                print_table(photos_data, prop_list, headers)
            else:
                headers = ["UUID", "Filename", "Created", "Kind", "Favorite", "Cloud"]
                keys = ["uuid", "filename", "date_created", "kind", "is_favorite", "cloud_status"]
                print_table(photos_data, keys, headers)
        else:
            print_json(photos_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def get_photo(
    uuid: str = typer.Argument(..., help="Photo UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a single photo by UUID.

    Examples:
        photos-app photos get "ABC123-DEF456"
        photos-app photos get "ABC123-DEF456" --table
    """
    try:
        client = get_client()

        # Search for photo by UUID
        photos = client.list_photos(limit=1000, include_hidden=True, include_videos=True)
        photo = next((p for p in photos if p.uuid == uuid), None)

        if not photo:
            print_error(f"Photo not found: {uuid}")
            raise typer.Exit(1)

        photo_data = photo.to_dict()

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in photo_data.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(photo_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("download")
def download_photos(
    destination: str = typer.Argument(..., help="Destination folder"),
    album: Optional[str] = typer.Option(
        None, "--album", "-a", help="Download from specific album"
    ),
    from_date: Optional[str] = typer.Option(
        None, "--from", "-f", help="Start date (YYYY-MM-DD)"
    ),
    to_date: Optional[str] = typer.Option(
        None, "--to", "-t", help="End date (YYYY-MM-DD)"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Max photos to download"),
    include_videos: bool = typer.Option(
        False, "--videos", "-v", help="Include videos"
    ),
):
    """Download/export photos to a destination folder.

    This command exports photos via Photos.app, which automatically
    handles downloading from iCloud if the photos are not stored locally.

    Examples:
        photos-app photos download ~/Desktop/export --limit 10
        photos-app photos download /tmp/photos --from 2024-01-01
        photos-app photos download /tmp/photos --album "ebaylisting"
    """
    try:
        client = get_client()

        from_dt = parse_date(from_date)
        to_dt = parse_date(to_date)

        # Get photos matching filters
        photos = client.list_photos(
            from_date=from_dt,
            to_date=to_dt,
            limit=limit,
            include_videos=include_videos,
            album=album,
        )

        if not photos:
            print_error("No photos match the criteria")
            raise typer.Exit(1)

        print_info(f"Exporting {len(photos)} photos to {destination}...")

        # Export via AppleScript
        dest_path = Path(destination)
        uuids = [p.uuid for p in photos]
        exported = client.export_photos(uuids, dest_path)

        if exported:
            print_success(f"Exported {len(exported)} photos")
            # Output exported paths
            for path in exported:
                typer.echo(str(path))
        else:
            print_error("No photos were exported")
            raise typer.Exit(1)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("count")
def count_photos():
    """Show total number of photos in the library."""
    try:
        client = get_client()
        count = client.get_photo_count()
        typer.echo(count)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
