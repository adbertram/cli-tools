"""Email commands."""
COMMAND_CREDENTIALS = {
    "analytics": [
        "api_key"
    ],
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "render": [
        "api_key"
    ],
    "send-draft": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}

from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.output import command

from ..client import get_client
from .common import confirm_delete, emit, parse_json_object, read_body


app = typer.Typer(help="Manage emails", no_args_is_help=True)


@app.command("list")
@command
def emails_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of emails"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List emails."""
    # filter_map translation happens in the client with Buttondown query params.
    emails = get_client().list_emails(limit=limit, filters=filter)
    emit(emails, table, properties, ["id", "subject", "status", "publish_date", "creation_date"])


@app.command("get")
@command
def emails_get(
    email_id: str = typer.Argument(..., help="Email ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get an email."""
    emit(get_client().get_email(email_id), table, properties, ["id", "subject", "status"])


@app.command("create")
@command
def emails_create(
    subject: str = typer.Option(..., "--subject", "-s", help="Email subject"),
    body: Optional[str] = typer.Option(None, "--body", help="Email body"),
    body_file: Optional[Path] = typer.Option(None, "--body-file", help="Read email body from file"),
    status: Optional[str] = typer.Option(None, "--status", help="Email status"),
    slug: Optional[str] = typer.Option(None, "--slug", help="Email slug"),
    description: Optional[str] = typer.Option(None, "--description", help="Archive description"),
    publish_date: Optional[str] = typer.Option(None, "--publish-date", help="Publish date"),
    email_type: Optional[str] = typer.Option(None, "--email-type", help="Email audience type"),
    archival_mode: Optional[str] = typer.Option(None, "--archival-mode", help="Archive visibility mode"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create an email."""
    email = get_client().create_email(
        subject=subject,
        body=read_body(body, body_file),
        status=status,
        slug=slug,
        description=description,
        publish_date=publish_date,
        email_type=email_type,
        archival_mode=archival_mode,
        metadata=parse_json_object(metadata, "--metadata"),
    )
    emit(email, table, properties, ["id", "subject", "status"])


@app.command("update")
@command
def emails_update(
    email_id: str = typer.Argument(..., help="Email ID"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="Email subject"),
    body: Optional[str] = typer.Option(None, "--body", help="Email body"),
    body_file: Optional[Path] = typer.Option(None, "--body-file", help="Read email body from file"),
    status: Optional[str] = typer.Option(None, "--status", help="Email status"),
    slug: Optional[str] = typer.Option(None, "--slug", help="Email slug"),
    description: Optional[str] = typer.Option(None, "--description", help="Archive description"),
    publish_date: Optional[str] = typer.Option(None, "--publish-date", help="Publish date"),
    email_type: Optional[str] = typer.Option(None, "--email-type", help="Email audience type"),
    archival_mode: Optional[str] = typer.Option(None, "--archival-mode", help="Archive visibility mode"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Update an email."""
    email = get_client().update_email(
        email_id,
        subject=subject,
        body=read_body(body, body_file),
        status=status,
        slug=slug,
        description=description,
        publish_date=publish_date,
        email_type=email_type,
        archival_mode=archival_mode,
        metadata=parse_json_object(metadata, "--metadata"),
    )
    emit(email, table, properties, ["id", "subject", "status"])


@app.command("delete")
@command
def emails_delete(
    email_id: str = typer.Argument(..., help="Email ID"),
    force: bool = typer.Option(False, "--force", "-F", help="Delete without confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete an email."""
    confirm_delete("email", email_id, force)
    emit(get_client().delete_email(email_id), table, None, ["ok", "action", "id"])


@app.command("send-draft")
@command
def emails_send_draft(
    email_id: str = typer.Argument(..., help="Email ID"),
    recipient: Optional[List[str]] = typer.Option(None, "--recipient", "-r", help="Recipient email; repeatable"),
    subscriber: Optional[List[str]] = typer.Option(None, "--subscriber", "-s", help="Subscriber ID; repeatable"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Send a draft email."""
    emit(
        get_client().send_draft(email_id, recipients=recipient, subscribers=subscriber),
        table,
        None,
        ["ok", "action", "id"],
    )


@app.command("render")
@command
def emails_render(
    email_id: str = typer.Argument(..., help="Email ID"),
    target: str = typer.Option(
        "email",
        "--target",
        help="Render target: 'email' (inlined for inbox) or 'html' (web archive chrome)",
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write rendered HTML to this file instead of stdout"
    ),
    open_browser: bool = typer.Option(
        False, "--open", help="Open the rendered HTML in the default browser"
    ),
):
    """Retrieve the rendered HTML of an email from the Buttondown API."""
    import os
    import subprocess
    import tempfile

    render = get_client().render_email(email_id, target)
    html = render.content

    if output is not None:
        output.write_text(html)
        typer.echo(f"Wrote {len(html)} bytes of rendered HTML to {output}")
    elif open_browser:
        pass
    else:
        typer.echo(html)

    if open_browser:
        target_path: Path
        if output is not None:
            target_path = output
        else:
            fd, tmp_path = tempfile.mkstemp(prefix=f"buttondown-render-{email_id}-", suffix=".html")
            os.close(fd)
            target_path = Path(tmp_path)
            target_path.write_text(html)
            typer.echo(f"Rendered HTML saved to {target_path}")
        subprocess.run(["open", str(target_path)], check=True)


@app.command("analytics")
@command
def emails_analytics(
    email_id: str = typer.Argument(..., help="Email ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get email analytics."""
    emit(
        get_client().get_email_analytics(email_id),
        table,
        properties,
        ["recipients", "deliveries", "opens", "clicks"],
    )
