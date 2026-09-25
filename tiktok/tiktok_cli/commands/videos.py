"""TikTok Direct Post video commands."""
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import handle_error, print_json, print_table

from ..posting import TikTokPostingClient

app = typer.Typer(help="Publish and inspect TikTok videos through Content Posting API")

COMMAND_CREDENTIALS = {
    "publish": ["custom"],
    "status": ["custom"],
}


@app.command("publish")
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
    try:
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
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("status")
def videos_status(
    publish_id: str = typer.Argument(..., help="TikTok publish_id returned by publish"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    try:
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
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
