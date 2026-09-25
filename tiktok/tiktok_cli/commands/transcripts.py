"""Transcripts commands for TikTok CLI."""
COMMAND_CREDENTIALS = {
    "download": ["no_auth"]
}

import typer
from typing import List
from pathlib import Path

from cli_tools_shared.output import command, print_success, print_error, print_info, print_table
from ..client import get_client, ClientError

app = typer.Typer(help="Download TikTok video transcripts")


def _format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_size(bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"


@app.command("download")
@command
def download(
    urls: List[str] = typer.Argument(..., help="TikTok video URL(s)"),
    output_dir: str = typer.Option(".", "--output-dir", "-o", help="Output directory"),
    format: str = typer.Option("srt", "--format", "-f", help="Subtitle format"),
    lang: str = typer.Option("en", "--lang", "-l", help="Subtitle language code"),
    auto_sub: bool = typer.Option(True, "--auto-sub/--no-auto-sub"),
    manual_sub: bool = typer.Option(False, "--manual-sub"),
    table: bool = typer.Option(False, "--table", "-t", help="Display results as a table"),
):
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
    except ClientError as e:
        print_error(f"Failed to download transcripts: {e}")
        raise typer.Exit(1)

    if table:
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
            })
        print_table(table_data, ["Title", "Duration", "File", "Size", "Format"])
    else:
        for result in results:
            print_success(f"Downloaded: {result['title']}")
            print_info(f"  Duration: {_format_duration(result['duration'])}")
            print_info(f"  File: {result['file_path']}")
            print_info(f"  Size: {_format_size(result['file_size'])}")
            print_info(f"  Format: {result['format']} ({result['language']})")

    print_success(f"Successfully downloaded {len(results)} transcript(s) to {output_dir}")
