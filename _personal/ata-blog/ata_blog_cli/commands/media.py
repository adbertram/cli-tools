"""Media commands for ATA Blog CLI.

`upload` writes to the static site's Cloudflare R2 media bucket, the site's
only media store.
"""
import typer
from pathlib import Path
from cli_tools_shared.output import command, print_json

from ..utils.images import upload_to_static_media

COMMAND_CREDENTIALS = {
    "upload": ["custom"],
}

app = typer.Typer(help="Upload media files (image, video, or caption file) to the static site (Cloudflare R2)")


@app.command("upload")
@command
def media_upload(
    file_path: str = typer.Argument(..., help="Path to the local media file (image, video, or caption file)"),
):
    """Upload a media file (image, video, or caption file) to the static site media bucket (Cloudflare R2).

    Any file with a guessable MIME type works, for example .webp, .mp4, or .srt.
    The object lands at a content-addressed wp-content/uploads/publisher/ key
    and the printed URL is publicly served by the site's media edge.

    Examples:
        ata-blog media upload ./posts/<page_id>/images/diagram.webp
        ata-blog media upload ./shorts/<post-slug>/short.mp4
        ata-blog media upload ./shorts/<post-slug>/short.srt
    """
    path = Path(file_path)
    if not path.is_file():
        raise typer.BadParameter(f"File not found: {file_path}")
    print_json(upload_to_static_media(path))
