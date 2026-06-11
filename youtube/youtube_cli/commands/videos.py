"""Videos commands for YouTube CLI."""
COMMAND_CREDENTIALS = {
    "chapters": ["no_auth"],
    "list": ["no_auth"],
    "get": ["no_auth"],
    "download": ["no_auth"],
}

import typer
from typing import List, Optional
from pathlib import Path

from ..client import get_client, ClientError, MAX_RESOLUTION_FORMATS, MAX_RESOLUTION_VALUES
from cli_tools_shared.output import print_success, print_error, print_info, print_table, print_json
from ..chapter_validation import validate_chapters_description

app = typer.Typer(help="Download YouTube videos")
chapters_app = typer.Typer(help="Validate YouTube video chapter timestamps", no_args_is_help=True)
app.add_typer(chapters_app, name="chapters")


def _format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_size(size_bytes: int) -> str:
    """Format file size in bytes to human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def _print_results(results: List[dict], table_mode: bool, output_dir: str):
    """Print download results in table or list format."""
    if table_mode:
        table_data = []
        for result in results:
            file_path = Path(result["file_path"])
            filename = file_path.name if file_path.exists() else result["file_path"]

            table_data.append({
                "Title": result["title"][:50] + "..." if len(result["title"]) > 50 else result["title"],
                "Duration": _format_duration(result["duration"]),
                "File": filename,
                "Size": _format_size(result["file_size"]),
                "Format": result["format"],
                "Quality": result["quality"],
            })

        columns = ["Title", "Duration", "File", "Size", "Format", "Quality"]
        print_table(table_data, columns)
    else:
        for result in results:
            print_success(f"\n✓ Downloaded: {result['title']}")
            print_info(f"  Duration: {_format_duration(result['duration'])}")
            print_info(f"  File: {result['file_path']}")
            print_info(f"  Size: {_format_size(result['file_size'])}")
            print_info(f"  Format: {result['format']} (quality: {result['quality']})")

    print_success(f"\nSuccessfully downloaded {len(results)} video(s) to {output_dir}")


def _format_upload_date(date_str: str) -> str:
    """Format YYYYMMDD to YYYY-MM-DD."""
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


@chapters_app.command("validate")
def chapters_validate(
    description: str = typer.Option(
        ...,
        "--description",
        help="Video description text to validate",
    ),
    duration_seconds: Optional[int] = typer.Option(
        None,
        "--duration-seconds",
        help="Video duration in seconds; enables final-chapter length validation",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Validate YouTube manual Video Chapters in a description."""
    if duration_seconds is not None and duration_seconds <= 0:
        print_error("--duration-seconds must be greater than 0")
        raise typer.Exit(1)

    result = validate_chapters_description(
        description,
        duration_seconds=duration_seconds,
    )

    if table:
        print_table(
            [
                {
                    "valid": result["valid"],
                    "chapter_count": result["chapter_count"],
                    "issues": len(result["issues"]),
                    "duration_checked": result["duration_checked"],
                }
            ],
            ["valid", "chapter_count", "issues", "duration_checked"],
            ["Valid", "Chapters", "Issues", "Duration Checked"],
        )
    else:
        print_json(result)


@app.command("list")
def list_videos(
    channel: str = typer.Argument(..., help="Channel handle or URL"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display results as a table",
    ),
    limit: int = typer.Option(
        0,
        "--limit",
        "-l",
        help="Max videos to list (0 = all)",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., title:contains:vlog)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include",
    ),
    exclude_shorts: bool = typer.Option(
        False,
        "--exclude-shorts",
        help="Exclude YouTube Shorts from results",
    ),
):
    """List all videos from a YouTube channel."""
    client = get_client()

    print_info(f"Discovering videos from channel: {channel}...")
    videos = client.list_channel_videos(channel, exclude_shorts=exclude_shorts)

    if filter:
        from cli_tools_shared.filters import apply_filters
        videos = apply_filters(videos, filter)

    if limit > 0:
        videos = videos[:limit]

    if properties:
        fields = [f.strip() for f in properties.split(",")]
        videos = [{k: v for k, v in video.items() if k in fields} for video in videos]

    print_info(f"Found {len(videos)} video(s)")

    if table:
        table_data = []
        for v in videos:
            table_data.append({
                "Title": v.get("title", "")[:60] + "..." if len(v.get("title", "")) > 60 else v.get("title", ""),
                "Duration": _format_duration(v["duration"]) if "duration" in v else "",
                "Uploaded": _format_upload_date(v["upload_date"]) if v.get("upload_date") else "",
                "URL": v.get("url", ""),
            })
        print_table(table_data, ["Title", "Duration", "Uploaded", "URL"])
    else:
        print_json(videos)


@app.command("get")
def get_video(
    url: str = typer.Argument(..., help="YouTube video URL"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as a table",
    ),
):
    """Get metadata for a single YouTube video."""
    client = get_client()
    metadata = client.get_video_metadata(url)

    result = {
        "title": metadata.get("title", "Unknown"),
        "url": url,
        "duration": metadata.get("duration", 0),
        "upload_date": metadata.get("upload_date", ""),
        "channel": metadata.get("channel", ""),
        "view_count": metadata.get("view_count", 0),
        "description": metadata.get("description", ""),
    }

    if table:
        print_table([{
            "Title": result["title"],
            "Duration": _format_duration(result["duration"]),
            "Uploaded": _format_upload_date(result["upload_date"]) if result["upload_date"] else "",
            "Channel": result["channel"],
            "Views": str(result["view_count"]),
        }], ["Title", "Duration", "Uploaded", "Channel", "Views"])
    else:
        print_json(result)


@app.command("download")
def download(
    urls: Optional[List[str]] = typer.Argument(None, help="YouTube video URL(s)"),
    channel: Optional[str] = typer.Option(
        None,
        "--channel",
        "-c",
        help="Download all videos from a channel (handle or URL)",
    ),
    output_dir: str = typer.Option(
        ".",
        "--output-dir",
        "-o",
        help="Output directory for videos",
    ),
    folder_path: Optional[str] = typer.Option(
        None,
        "--folder-path",
        help="Folder to compare and sync into when using --sync",
    ),
    format: str = typer.Option(
        "mp4",
        "--format",
        "-f",
        help="Video container format (mp4, mkv, webm)",
    ),
    quality: str = typer.Option(
        "best",
        "--quality",
        "-q",
        help="Quality selection (best, worst, or yt-dlp format code)",
    ),
    max_resolution: Optional[str] = typer.Option(
        None,
        "--max-resolution",
        help=f"Maximum video resolution preset: {MAX_RESOLUTION_VALUES}",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display results as a table",
    ),
    exclude_shorts: bool = typer.Option(
        False,
        "--exclude-shorts",
        help="Exclude YouTube Shorts from download",
    ),
    sync: bool = typer.Option(
        False,
        "--sync",
        help="With --channel, download only recent videos missing from --folder-path",
    ),
    limit: int = typer.Option(
        0,
        "--limit",
        "-l",
        help="Max videos to download (0 = all, applies to --channel)",
    ),
):
    """Download one or more YouTube videos, or all videos from a channel."""
    if not urls and not channel:
        print_error("Provide video URL(s) or --channel")
        raise typer.Exit(1)
    if sync and not channel:
        print_error("--sync requires --channel")
        raise typer.Exit(1)
    if sync and not folder_path:
        print_error("--sync requires --folder-path")
        raise typer.Exit(1)
    if folder_path and not sync:
        print_error("--folder-path is only valid with --sync")
        raise typer.Exit(1)
    if max_resolution:
        if quality != "best":
            print_error("Use --quality or --max-resolution, not both")
            raise typer.Exit(1)
        if max_resolution not in MAX_RESOLUTION_FORMATS:
            print_error(f"Invalid max resolution: {max_resolution}. Valid values: {MAX_RESOLUTION_VALUES}")
            raise typer.Exit(1)

    client = get_client()

    if sync:
        discovery_limit = limit if limit > 0 else 50
        print_info(f"Discovering latest {discovery_limit} video(s) from channel: {channel}...")
        videos = client.list_channel_videos(
            channel,
            exclude_shorts=exclude_shorts,
            limit=discovery_limit,
        )
        existing_titles = client.get_folder_video_titles(folder_path)
        missing_videos = [
            video for video in videos
            if client.get_video_title_key(video["title"]) not in existing_titles
        ]
        print_info(f"Found {len(missing_videos)} missing video(s) out of {len(videos)} discovered.")
        results = client.download_videos(
            urls=[video["url"] for video in missing_videos],
            output_dir=folder_path,
            format=format,
            quality=quality,
            max_resolution=max_resolution,
        )
        output_dir = folder_path
    elif channel:
        print_info(f"Discovering videos from channel: {channel}...")
        video_urls = client.get_channel_video_urls(
            channel,
            exclude_shorts=exclude_shorts,
            limit=limit,
        )
        print_info(f"Downloading {len(video_urls)} video(s)...")
        results = client.download_videos(
            urls=video_urls,
            output_dir=output_dir,
            format=format,
            quality=quality,
            max_resolution=max_resolution,
        )
    else:
        print_info(f"Downloading {len(urls)} video(s)...")
        results = client.download_videos(
            urls=urls,
            output_dir=output_dir,
            format=format,
            quality=quality,
            max_resolution=max_resolution,
        )

    _print_results(results, table, output_dir)
