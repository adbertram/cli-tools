"""Album commands for listing and creating albums."""
import subprocess
from typing import Optional, List

import typer

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_error, print_success, print_info, print_table
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

COMMAND_CREDENTIALS = {
    "add-photos": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "enhance": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "move": [
        "custom"
    ],
    "open": [
        "custom"
    ]
}

app = typer.Typer(help="Album operations")


@app.command("open")
def open_app():
    """Open the Photos app to the Albums view.

    Launches Photos.app and navigates to My Albums in the sidebar.

    Examples:
        photos-app albums open
    """
    script = '''
        tell application "Photos" to activate
        delay 0.5
        tell application "System Events"
            tell process "Photos"
                try
                    set sidebarOutline to outline 1 of scroll area 2 of splitter group 1 of window 1
                    repeat with r in (every row of sidebarOutline)
                        try
                            if value of static text 1 of UI element 1 of r is "Albums" then
                                select r
                                exit repeat
                            end if
                        end try
                    end repeat
                end try
            end tell
        end tell
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True)
    if result.returncode != 0:
        # Fallback: just open the app
        subprocess.run(["open", "-a", "Photos"])
    print_success("Opened Photos app")


@app.command("list")
def list_albums(
    include_system: bool = typer.Option(
        False, "--system", "-s", help="Include system albums"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    exclude_folder: Optional[List[str]] = typer.Option(None, "--exclude-folder", help="Exclude albums in folder"),
):
    """List all albums in the Photos library.

    By default shows only user-created albums. Use --system to include
    system albums (imports, sync progress, etc.).

    Examples:
        photos-app albums list
        photos-app albums list --system
        photos-app albums list --limit 10
        photos-app albums list --filter "title:like:%Vacation%"
        photos-app albums list --table
        photos-app albums list --properties uuid,title,photo_count
        photos-app albums list --exclude-folder "Completed eBay Listings"
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
        albums = client.list_albums(include_system=include_system, exclude_folders=exclude_folder)

        if not albums:
            print_info("No albums found")
            if not table:
                print_json([])
            return

        # Convert to dictionaries
        albums_data = [a.to_dict() for a in albums]

        # Apply client-side filtering
        if filter:
            albums_data = apply_filters(albums_data, filter)

        # Apply limit
        albums_data = albums_data[:limit]

        if not albums_data:
            print_info("No albums match the filters")
            if not table:
                print_json([])
            return

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            albums_data = [{k: v for k, v in album.items() if k in prop_list} for album in albums_data]

        # Output
        if table:
            if properties:
                headers = [p.strip().replace("_", " ").title() for p in properties.split(",")]
                print_table(albums_data, prop_list, headers)
            else:
                headers = ["UUID", "Title", "Photos", "Videos", "Created"]
                keys = ["uuid", "title", "photo_count", "video_count", "date_created"]
                print_table(albums_data, keys, headers)
        else:
            print_json(albums_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def get_album(
    identifier: str = typer.Argument(..., help="Album name or UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a single album by name or UUID.

    Examples:
        photos-app albums get "Vacation 2024"
        photos-app albums get "5152941D-A164-4979-A624-C876D56EA38A" --table
    """
    try:
        client = get_client()
        albums = client.list_albums()
        album = next(
            (a for a in albums if a.uuid == identifier or a.title.lower() == identifier.lower()),
            None,
        )

        if not album:
            print_error(f"Album not found: {identifier}")
            raise typer.Exit(1)

        album_data = album.to_dict()

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in album_data.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(album_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("create")
def create_album(
    name: str = typer.Argument(..., help="Name for the new album"),
):
    """Create a new album in the Photos library.

    Creates an empty album with the specified name. Use Photos.app to
    add photos to the album.

    Examples:
        photos-app albums create "Vacation 2024"
        photos-app albums create "Family Photos"
    """
    try:
        client = get_client()
        album = client.create_album(name)

        print_success(f"Created album '{album.title}'")
        print_json(album.to_dict())

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
def delete_album(
    name: str = typer.Argument(..., help="Name of the album to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete an album from the Photos library.

    This only deletes the album itself, not the photos in it.
    The photos will remain in your library.

    Examples:
        photos-app albums delete "Old Album"
        photos-app albums delete "Temp Album" --yes
    """
    try:
        if not yes:
            confirm = typer.confirm(f"Delete album '{name}'? (photos will not be deleted)")
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client = get_client()
        client.delete_album(name)

        print_success(f"Deleted album '{name}'")

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("move")
def move_album(
    name: str = typer.Argument(..., help="Name of the album to move"),
    folder: str = typer.Option(..., "--folder", "-f", help="Target folder name"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Move an album into a folder.

    Moves the specified album into the target folder. The folder is
    auto-created if it doesn't exist. Photos in the album are preserved.

    Examples:
        photos-app albums move "ebay-listing-20240101" --folder "Completed eBay Listings"
        photos-app albums move "Old Album" -f "Archive" --yes
    """
    try:
        if not yes:
            confirm = typer.confirm(f"Move album '{name}' into folder '{folder}'?")
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client = get_client()
        album = client.move_album_to_folder(name, folder)

        print_success(f"Moved album '{name}' into folder '{folder}'")
        print_json(album.to_dict())

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("enhance")
def enhance_album(
    name: str = typer.Argument(..., help="Album name to enhance photos in"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max photos to enhance"),
    delay: float = typer.Option(1.5, "--delay", "-d", help="Seconds between UI steps"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Auto-enhance all photos in an album.

    Applies the built-in Auto Enhance (Cmd+E) to each photo in the album
    sequentially via UI automation. Your computer will be unusable during
    the batch — Photos.app must stay in the foreground.

    Note: Auto-enhance is a toggle. Running on already-enhanced photos
    will REMOVE the enhancement.

    Requires Accessibility permissions for System Events.

    Examples:
        photos-app albums enhance "ebaylisting-boxes"
        photos-app albums enhance "ebaylisting-boxes" --limit 10
        photos-app albums enhance "ebaylisting-boxes" --delay 2.0 --yes
    """
    try:
        client = get_client()
        photos = client.list_photos(album=name, limit=limit)

        if not photos:
            print_error(f"Album '{name}' not found or is empty")
            raise typer.Exit(1)

        if not yes:
            confirm = typer.confirm(
                f"Auto-enhance {len(photos)} photo(s) in '{name}'? "
                "(computer unusable during batch, toggle removes existing enhancements)"
            )
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        succeeded = 0
        failed = 0
        for i, photo in enumerate(photos, 1):
            print_info(f"Enhancing photo {i}/{len(photos)}: {photo.uuid}...")
            try:
                client.auto_enhance_photo(photo.uuid, delay=delay)
                succeeded += 1
            except ClientError as e:
                print_error(f"Failed: {e}")
                failed += 1

        if failed == 0:
            print_success(f"Enhanced {succeeded}/{len(photos)} photos")
        else:
            print_info(f"Enhanced {succeeded}/{len(photos)} photos ({failed} failed)")

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("add-photos")
def add_photos(
    album: str = typer.Option(..., "--album", "-a", help="Name of the target album"),
    photo_ids: str = typer.Option(..., "--photo-ids", "-p", help="Comma-separated photo UUIDs"),
):
    """Add photos to an existing album.

    Adds one or more photos (by UUID) to the specified album.
    Photo UUIDs can be obtained from 'photos-app photos list'.

    Examples:
        photos-app albums add-photos --album "Vacation 2024" --photo-ids "ABC123,DEF456"
        photos-app albums add-photos -a "Family" -p "UUID1,UUID2,UUID3"

        # Add photos from a list command:
        UUIDS=$(photos-app photos list --limit 5 | jq -r '.[].uuid' | tr '\\n' ',' | sed 's/,$//')
        photos-app albums add-photos -a "My Album" -p "$UUIDS"
    """
    try:
        # Parse photo IDs
        uuids = [uuid.strip() for uuid in photo_ids.split(",") if uuid.strip()]

        if not uuids:
            print_error("No photo IDs provided")
            raise typer.Exit(1)

        client = get_client()
        added_count = client.add_photos_to_album(album, uuids)

        if added_count == 0:
            print_info("No matching photos found to add")
        elif added_count == len(uuids):
            print_success(f"Added {added_count} photo(s) to album '{album}'")
        else:
            print_success(f"Added {added_count} of {len(uuids)} photo(s) to album '{album}'")

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
