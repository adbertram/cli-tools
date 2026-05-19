"""Medium post commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.output import command

from ..client import get_client
from .common import emit_row, read_content


COMMAND_CREDENTIALS = {
    "create": ["browser_session"],
}

app = typer.Typer(help="Create Medium drafts", no_args_is_help=True)


@app.command("create")
@command
def posts_create(
    title: str = typer.Option(..., "--title", help="Post title"),
    content: Optional[str] = typer.Option(None, "--content", help="Post body text or HTML"),
    content_file: Optional[Path] = typer.Option(None, "--content-file", help="Read post body from a UTF-8 file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create a Medium draft in the web composer."""
    post = get_client().create_post(
        title=title,
        content=read_content(content, content_file),
    )
    emit_row(
        post,
        table,
        properties,
        columns=["title", "draft_url", "edit_url"],
    )
