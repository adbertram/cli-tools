"""Video commands for eBay CLI.

Uses the eBay Commerce Media API to create and upload listing videos.
API Docs: https://developer.ebay.com/api-docs/commerce/media/resources/video/methods/createVideo
"""
from cli_tools_shared.output import command
COMMAND_CREDENTIALS = {
    "create": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
}

from typing import Optional

import typer

from ..client import get_client
from ..parsers import format_local_time
from ..video import (
    VIDEO_EXTENSIONS,
    default_title_for,
    prepare_video_for_upload,
    upload_prepared_video,
    video_prep_message,
)
from cli_tools_shared.output import print_info, print_json, print_table

app = typer.Typer(help="Manage eBay listing videos via Media API")

TABLE_COLUMNS = ["videoId", "status", "statusMessage", "size", "title", "expirationDate"]
TABLE_HEADERS = ["Video ID", "Status", "Message", "Size", "Title", "Expires"]

_EXTENSION_LIST = ", ".join(sorted(VIDEO_EXTENSIONS))


def _video_table_row(result: dict, video_id: str) -> dict:
    """Flatten a Media API video record into table-friendly columns."""
    return {
        "videoId": result.get("videoId", video_id),
        "status": result.get("status", ""),
        "statusMessage": result.get("statusMessage", ""),
        "size": result.get("size", ""),
        "title": result.get("title", ""),
        "expirationDate": format_local_time(result.get("expirationDate", "")),
    }


@app.command("create")
@command
def videos_create(
    path: str = typer.Argument(
        ..., help=f"Local video file to upload ({_EXTENSION_LIST})"
    ),
    title: Optional[str] = typer.Option(
        None, "--title", help="Video title (default: derived from the file name)"
    ),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Optional video description"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Create a video resource and upload its bytes to eBay.

    Files that are not already H.264 in an MP4/MOV container are transcoded to a
    temporary H.264 MP4 first; the original file is never modified. The byte size
    sent to eBay is the size of the file that is actually uploaded.

    Videos expire 30 days after upload, and shoppers can only view them in eBay's
    iOS and Android apps.

    Examples:
        ebay seller videos create ./clip.mov
        ebay seller videos create ./clip.mov --title "Bulk LEGO lot walkthrough"
        ebay seller videos create ./clip.mov --description "Close-up of the minifigures" --table
    """
    resolved_title = title or default_title_for(path)
    prepared = prepare_video_for_upload(path)

    try:
        print_info(video_prep_message(prepared))

        client = get_client()
        video_id = upload_prepared_video(
            client,
            prepared,
            title=resolved_title,
            description=description,
        )
        print_info(f"Uploaded {prepared.size} bytes to {video_id}")

        result = {
            "videoId": video_id,
            "title": resolved_title,
            "size": prepared.size,
            "transcoded": prepared.transcoded,
            "sourceCodec": prepared.source_codec,
            "outputCodec": prepared.output_codec,
        }

        if table:
            print_table(
                [_video_table_row(result, video_id)],
                TABLE_COLUMNS,
                TABLE_HEADERS,
            )
        else:
            print_json(result)
    finally:
        prepared.cleanup()


@app.command("get")
@command
def videos_get(
    video_id: str = typer.Argument(..., help="The eBay video ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get video metadata and processing status from eBay.

    Status moves PENDING_UPLOAD -> PROCESSING -> LIVE; failures appear as
    PROCESSING_FAILED or BLOCKED with a statusMessage explaining why.

    Examples:
        ebay seller videos get 1a2b3c4d
        ebay seller videos get 1a2b3c4d --table
    """
    client = get_client()
    result = client.get_video(video_id)

    if table:
        print_table([_video_table_row(result, video_id)], TABLE_COLUMNS, TABLE_HEADERS)
    else:
        print_json(result)
