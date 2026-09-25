"""Facebook Page Reels publishing commands."""
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import handle_error, print_json, print_table

from ..graph_api import FacebookGraphClient

app = typer.Typer(help="Publish and inspect Facebook Page Reels")

COMMAND_CREDENTIALS = {
    "publish": ["oauth_authorization_code"],
    "status": ["oauth_authorization_code"],
}


@app.command("publish")
def reels_publish(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Video file to publish"),
    page_id: str = typer.Option(..., "--page", help="Facebook Page ID"),
    title: str = typer.Option("", "--title", help="Reel title"),
    description: str = typer.Option("", "--description", help="Reel description/caption"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Upload a local video and publish it as a Facebook Page Reel."""
    try:
        result = FacebookGraphClient().publish_reel(
            page_id,
            file,
            title=title,
            description=description,
        )
        if table:
            columns = ["page_id", "page_name", "video_id", "published", "status"]
            print_table([result], columns, [c.replace("_", " ").title() for c in columns])
        else:
            print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("status")
def reels_status(
    video_id: str = typer.Argument(..., help="Facebook Reel/video ID"),
    page_id: str = typer.Option(..., "--page", help="Facebook Page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """Get the processing/publishing status of a Facebook Page Reel."""
    try:
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
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
