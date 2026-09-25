"""Facebook Page Reels publishing commands."""
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import (
    command,
    confirm_destructive_action,
    print_json,
    print_table,
)

from ..graph_api import FacebookGraphClient

app = typer.Typer(help="Publish and inspect Facebook Page Reels")

COMMAND_CREDENTIALS = {
    "publish": ["oauth_authorization_code"],
    "status": ["oauth_authorization_code"],
    "delete": ["oauth_authorization_code"],
}


@app.command("publish")
@command
def reels_publish(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Video file to publish"),
    page_id: str = typer.Option(..., "--page", help="Facebook Page ID"),
    title: str = typer.Option("", "--title", help="Reel title"),
    description: str = typer.Option("", "--description", help="Reel description/caption"),
    draft: bool = typer.Option(
        False, "--draft", help="Save the Reel as an unpublished Page draft instead of publishing it"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Upload a local video and publish it (or save it as a draft) as a Facebook Page Reel."""
    result = FacebookGraphClient().publish_reel(
        page_id,
        file,
        title=title,
        description=description,
        draft=draft,
    )
    if table:
        columns = ["page_id", "page_name", "video_id", "video_state", "published", "status"]
        print_table([result], columns, [c.replace("_", " ").title() for c in columns])
    else:
        print_json(result)


@app.command("status")
@command
def reels_status(
    video_id: str = typer.Argument(..., help="Facebook Reel/video ID"),
    page_id: str = typer.Option(..., "--page", help="Facebook Page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """Get the processing/publishing status of a Facebook Page Reel."""
    result = FacebookGraphClient().get_reel_status(page_id, video_id)
    if properties:
        result = apply_properties_filter([result], properties)[0]
    columns = (
        [field.strip() for field in properties.split(",") if field.strip()]
        if properties
        else ["page_id", "page_name", "video_id", "status"]
    )
    if table:
        print_table([result], columns, [c.replace("_", " ").title() for c in columns])
    else:
        print_json(result)


@app.command("delete")
@command
def reels_delete(
    video_id: str = typer.Argument(..., help="Facebook Reel/video ID"),
    page_id: str = typer.Option(..., "--page", help="Facebook Page ID that owns the Reel"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Permanently delete a Facebook Page Reel."""
    confirm_destructive_action(
        f"Permanently delete Facebook Reel {video_id}?",
        assume_yes=yes,
        action_description=f"delete Facebook Reel {video_id}",
    )
    print_json(FacebookGraphClient().delete_reel(page_id, video_id))
