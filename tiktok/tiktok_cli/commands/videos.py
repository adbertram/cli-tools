"""TikTok Direct Post video commands."""
from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import ClientError, command, print_json, print_table

from ..client import get_web_client
from ..posting import TikTokPostingClient

app = typer.Typer(help="Publish, inspect, list, and delete TikTok videos")

COMMAND_CREDENTIALS = {
    "publish": ["custom"],
    "status": ["custom"],
    "list": ["browser_session"],
    "get": ["browser_session"],
    "delete": ["browser_session"],
}
_VIDEO_COLUMNS = ["id", "url", "caption", "author", "created_at"]
_USERNAME_HELP = "TikTok username whose posts to read (private posts need that account's session)"


@app.command("publish")
@command
def videos_publish(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Video file to publish"),
    title: str = typer.Option("", "--title", help="TikTok post caption/title"),
    privacy: str = typer.Option(
        "SELF_ONLY",
        "--privacy",
        help="TikTok creator privacy level",
    ),
    disable_comment: bool = typer.Option(False, "--disable-comment", help="Disable comments"),
    disable_duet: bool = typer.Option(False, "--disable-duet", help="Disable Duet"),
    disable_stitch: bool = typer.Option(False, "--disable-stitch", help="Disable Stitch"),
    ai_generated: bool = typer.Option(
        False, "--ai-generated", help="Label the video as AI-generated content"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Publish a video through the Content Posting API (Direct Post)."""
    result = TikTokPostingClient().publish_video(
        file,
        title=title,
        privacy_level=privacy,
        disable_comment=disable_comment,
        disable_duet=disable_duet,
        disable_stitch=disable_stitch,
        is_aigc=ai_generated,
    )
    if table:
        columns = ["publish_id", "status", "fail_reason", "uploaded_bytes"]
        print_table([result], columns, [c.replace("_", " ").title() for c in columns])
    else:
        print_json(result)


@app.command("status")
@command
def videos_status(
    publish_id: str = typer.Argument(..., help="TikTok publish_id returned by publish"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """Fetch a Direct Post's publish status by publish_id."""
    result = TikTokPostingClient().status(publish_id)
    if properties:
        result = apply_properties_filter([result], properties)[0]
    columns = (
        [field.strip() for field in properties.split(",") if field.strip()]
        if properties
        else ["publish_id", "status", "fail_reason", "uploaded_bytes"]
    )
    if table:
        print_table([result], columns, [c.replace("_", " ").title() for c in columns])
    else:
        print_json(result)


def _print_videos(videos: list, table: bool, properties: Optional[str]) -> None:
    if properties:
        videos = apply_properties_filter(videos, properties)
    if table:
        columns = [p.strip() for p in properties.split(",")] if properties else _VIDEO_COLUMNS
        print_table(videos, columns, columns)
    else:
        print_json(videos)


@app.command("list")
@command
def videos_list(
    username: str = typer.Option(..., "--username", "-u", help=_USERNAME_HELP),
    table: bool = typer.Option(False, "--table", "-t", help="Display results as a table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """List a profile's posted videos, including private ones for your own account."""
    if filter:
        try:
            validate_filters(filter)
        except FilterValidationError as e:
            raise ClientError(str(e)) from e
    client = get_web_client()
    try:
        videos = client.list_posted_videos(username, limit=limit)
    finally:
        client.close()
    if filter:
        videos = apply_filters(videos, filter)
    _print_videos(videos, table, properties)


@app.command("get")
@command
def videos_get(
    video_id: str = typer.Argument(..., help="TikTok video id"),
    username: str = typer.Option(..., "--username", "-u", help=_USERNAME_HELP),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as a table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """Get one of a profile's posted videos by id."""
    client = get_web_client()
    try:
        video = client.get_posted_video(username, video_id)
    finally:
        client.close()
    if table:
        _print_videos([video], True, properties)
    else:
        print_json(apply_properties_filter([video], properties)[0] if properties else video)


@app.command("delete")
@command
def videos_delete(
    video_id: str = typer.Argument(..., help="TikTok video id to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm permanent deletion"),
):
    """Permanently delete one of your TikTok videos."""
    if not yes:
        raise ClientError("Refusing to delete TikTok video without --yes.")
    client = get_web_client()
    try:
        print_json(client.delete_video(video_id))
    finally:
        client.close()
