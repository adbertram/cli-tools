"""Transcripts commands for YouTube CLI."""
COMMAND_CREDENTIALS = {
    "download": ["no_auth"],
}

import typer
from typing import List
from pathlib import Path

from ..client import get_client, ClientError
from cli_tools_shared.output import print_success, print_error, print_info, print_table

app = typer.Typer(help="Download YouTube video transcripts")


def _format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_size(bytes: int) -> str:
    """Format file size in bytes to human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"


@app.command("download")
def download(
    urls: List[str] = typer.Argument(..., help="YouTube video URL(s)"),
    output_dir: str = typer.Option(
        ".",
        "--output-dir",
        "-o",
        help="Output directory for transcripts",
    ),
    format: str = typer.Option(
        "srt",
        "--format",
        "-f",
        help="Subtitle format (srt, vtt, txt)",
    ),
    lang: str = typer.Option(
        "en",
        "--lang",
        "-l",
        help="Subtitle language code",
    ),
    auto_sub: bool = typer.Option(
        True,
        "--auto-sub/--no-auto-sub",
        help="Download auto-generated subtitles",
    ),
    manual_sub: bool = typer.Option(
        False,
        "--manual-sub",
        help="Prefer manual subtitles over auto-generated",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display results as a table",
    ),
):
    """Download transcripts for one or more YouTube videos."""
    client = get_client()

    print_info(f"Downloading transcripts for {len(urls)} video(s)...")

    try:
        results = client.download_transcripts(
            urls=urls,
            output_dir=output_dir,
            format=format,
            lang=lang,
            auto_sub=auto_sub,
            manual_sub=manual_sub,
        )

        if table:
            # Prepare table data
            table_data = []
            for result in results:
                # Get just the filename from the full path
                file_path = Path(result["file_path"])
                filename = file_path.name if file_path.exists() else result["file_path"]

                table_data.append({
                    "Title": result["title"][:50] + "..." if len(result["title"]) > 50 else result["title"],
                    "Duration": _format_duration(result["duration"]),
                    "File": filename,
                    "Size": _format_size(result["file_size"]),
                    "Format": result["format"],
                })

            columns = ["Title", "Duration", "File", "Size", "Format"]
            print_table(table_data, columns)
        else:
            # Print results in list format
            for result in results:
                print_success(f"\n✓ Downloaded: {result['title']}")
                print_info(f"  Duration: {_format_duration(result['duration'])}")
                print_info(f"  File: {result['file_path']}")
                print_info(f"  Size: {_format_size(result['file_size'])}")
                print_info(f"  Format: {result['format']} ({result['language']})")

        print_success(f"\nSuccessfully downloaded {len(results)} transcript(s) to {output_dir}")

    except ClientError as e:
        print_error(f"Failed to download transcripts: {e}")
        raise typer.Exit(1)
