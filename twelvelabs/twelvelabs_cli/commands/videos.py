"""Videos commands for TwelveLabs CLI."""
import typer
from typing import Optional, List
from pathlib import Path

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_info, print_error, handle_error
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared import FilterMap


app = typer.Typer(help="Manage videos in TwelveLabs indexes", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def videos_list(
    index_id: str = typer.Argument(..., help="The index ID to list videos from"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of videos to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List videos in an index.

    Examples:
        twelvelabs videos list INDEX_ID
        twelvelabs videos list INDEX_ID --table
        twelvelabs videos list INDEX_ID --limit 10
        twelvelabs videos list INDEX_ID --filter "metadata.filename:contains:clip"
        twelvelabs videos list INDEX_ID --properties "id,metadata.filename"
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
        videos = client.list_videos(index_id, limit=limit)

        # Apply client-side filters (TwelveLabs API doesn't support server-side filtering)
        if filter:
            videos = apply_filters(videos, filter)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            videos = extract_fields(videos, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(videos, fields, fields)
            else:
                print_table(
                    videos,
                    ["id", "index_id", "created_at"],
                    ["ID", "Index ID", "Created"],
                )
        else:
            print_json(videos)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def videos_get(
    index_id: str = typer.Argument(..., help="The index ID"),
    video_id: str = typer.Argument(..., help="The video ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get details for a specific video.

    Examples:
        twelvelabs videos get INDEX_ID VIDEO_ID
        twelvelabs videos get INDEX_ID VIDEO_ID --table
        twelvelabs videos get INDEX_ID VIDEO_ID --properties "id,duration"
    """
    try:
        client = get_client()
        video = client.get_video(index_id, video_id)

        # Apply properties field selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            video = extract_fields([video], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([video], fields, fields)
            else:
                item_dict = model_to_dict(video)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(video)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("upload")
def videos_upload(
    index_id: str = typer.Argument(..., help="The index ID to upload to"),
    video_path: str = typer.Argument(..., help="Path to the video file"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for indexing to complete (default: wait)"),
    timeout: int = typer.Option(600, "--timeout", help="Timeout in seconds when waiting (default: 600)"),
    skip_duplicate: bool = typer.Option(True, "--skip-duplicate/--force-upload", help="Skip if video with same filename exists (default: skip)"),
):
    """
    Upload a video to an index.

    By default, waits for the video to be indexed before returning.
    Use --no-wait to return immediately after upload starts.

    Examples:
        twelvelabs videos upload INDEX_ID /path/to/video.mp4
        twelvelabs videos upload INDEX_ID video.mp4 --no-wait
        twelvelabs videos upload INDEX_ID video.mp4 --force-upload
        twelvelabs videos upload INDEX_ID video.mp4 --timeout 300
    """
    try:
        # Validate file exists
        path = Path(video_path)
        if not path.exists():
            print_error(f"Video file not found: {video_path}")
            raise typer.Exit(1)

        client = get_client()

        if wait:
            print_info(f"Uploading {path.name} and waiting for indexing...")
        else:
            print_info(f"Uploading {path.name}...")

        task = client.upload_video(
            index_id=index_id,
            video_path=str(path),
            wait=wait,
            timeout=timeout,
            check_duplicate=skip_duplicate,
        )

        if task.id == "existing":
            print_info(f"Video already exists in index with ID: {task.video_id}")
        elif task.status.value == "ready":
            print_success(f"Video uploaded and indexed successfully")
            print_info(f"Video ID: {task.video_id}")
        else:
            print_success(f"Upload task created")
            print_info(f"Task ID: {task.id}")
            print_info(f"Status: {task.status.value}")

        print_json(task)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def videos_delete(
    index_id: str = typer.Argument(..., help="The index ID"),
    video_id: str = typer.Argument(..., help="The video ID to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
):
    """
    Delete a video from an index.

    Examples:
        twelvelabs videos delete INDEX_ID VIDEO_ID
        twelvelabs videos delete INDEX_ID VIDEO_ID --force
    """
    try:
        if not force:
            confirm = typer.confirm(f"Are you sure you want to delete video {video_id}?")
            if not confirm:
                print_info("Deletion cancelled")
                raise typer.Exit(0)

        client = get_client()
        client.delete_video(index_id, video_id)
        print_success(f"Video {video_id} deleted successfully")

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "upload": [
        "custom"
    ]
}
