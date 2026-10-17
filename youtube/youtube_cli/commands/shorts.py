"""YouTube Shorts upload adapter.

YouTube does not expose a separate Shorts upload endpoint. This command delegates
to the existing authenticated channel video uploader; YouTube classifies eligible
vertical/square uploads as Shorts.
"""
from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.output import command

from ..models import PrivacyStatus
from . import channel

app = typer.Typer(help="Upload YouTube Shorts through the Data API")

COMMAND_CREDENTIALS = {
    "upload": ["custom"],
}


@app.command("upload")
@command
def shorts_upload(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Short video file"),
    title: str = typer.Option(..., "--title", help="Video title"),
    description: str = typer.Option("", "--description", help="Video description"),
    tags: Optional[List[str]] = typer.Option(
        None, "--tag", help="Video tag (repeatable)"
    ),
    category_id: str = typer.Option(
        "22", "--category-id", help="YouTube category ID"
    ),
    privacy: PrivacyStatus = typer.Option(
        PrivacyStatus.PRIVATE,
        "--privacy",
        help="Privacy status: private, unlisted, or public",
    ),
    publish_at: Optional[str] = typer.Option(
        None,
        "--publish-at",
        help="Scheduled publish time in RFC 3339; requires private privacy",
    ),
    made_for_kids: bool = typer.Option(
        False,
        "--made-for-kids/--not-made-for-kids",
        help="Mark video as made for kids",
    ),
    thumbnail: Optional[Path] = typer.Option(
        None,
        "--thumbnail",
        exists=True,
        dir_okay=False,
        help="Optional thumbnail image",
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Upload a video intended to be classified by YouTube as a Short."""
    return channel.videos_upload(
        file=file,
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        privacy=privacy,
        publish_at=publish_at,
        made_for_kids=made_for_kids,
        thumbnail=thumbnail,
        include_recommended_chapters=False,
        profile=profile,
    )
