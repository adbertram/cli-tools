"""Prepare and inspect journaled Studio operations; publish only with --yes."""
from pathlib import Path

import typer
from cli_tools_shared.output import command, print_json, print_table

from ..config import get_config
from ..studio import parse_response
from ..studio_publishing import StudioPublisher, StudioPublishError, validate_policy

MAX_POLICY_BYTES = 64 * 1024  # Fixed schema plus a 4000-character escaped caption.

app = typer.Typer(help="Prepare, publish, and reconcile owned Studio drafts", no_args_is_help=True)
COMMAND_CREDENTIALS = {name: ["browser_session"] for name in ("prepare", "publish", "reconcile")} | {"status": ["no_auth"]}


def _print_operation(result, table):
    if table:
        columns = ["request_id", "state", "draft_id", "item_id", "url"]
        print_table([result], columns, columns)
    else:
        print_json(result)


@app.command("prepare")
@command
def studio_prepare(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Exact local MP4 to upload privately"),
    policy: Path = typer.Option(..., "--policy", exists=True, dir_okay=False, help="Explicit version 1 Studio policy JSON"),
    request_id: str = typer.Option(..., "--request-id", help="Canonical UUID binding this operation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Upload privately, verify disclosure controls, and retain the owned draft.

    Policy fields: schema_version=1, profile, account_id (string), username,
    caption, audience=Everyone, timing=now, disclosure=branded_content,
    music_rights_confirmed=true. Caption is used verbatim.
    """
    with policy.open("rb") as stream:
        payload = stream.read(MAX_POLICY_BYTES + 1)
    if len(payload) > MAX_POLICY_BYTES:
        raise StudioPublishError("Studio policy exceeds the 64 KiB input limit.")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise StudioPublishError("Studio policy must be UTF-8 JSON.") from None
    checked = validate_policy(parse_response(text))
    publisher = StudioPublisher(get_config())
    try:
        result = publisher.prepare(file, checked, request_id)
    finally:
        publisher.close()
    _print_operation(result, table)


@app.command("publish")
@command
def studio_publish(
    request_id: str = typer.Argument(..., help="Prepared operation UUID"),
    yes: bool = typer.Option(False, "--yes", help="Explicitly authorize the single public Post action"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Reverify and publish one exact owned draft; never retry unknown outcomes."""
    if not yes:
        raise StudioPublishError("Refusing Studio public Post without --yes.")
    publisher = StudioPublisher(get_config())
    try:
        def authorize(_binding):
            if not yes:
                raise StudioPublishError("Refusing Studio public Post without --yes.")
        result = publisher.publish(request_id, before_public_action=authorize)
    finally:
        publisher.close()
    _print_operation(result, table)


@app.command("status")
@command
def studio_status(
    request_id: str = typer.Argument(..., help="Operation UUID to read locally"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Read the profile's operation journal without remote browser actions."""
    publisher = StudioPublisher(get_config())
    try:
        result = publisher.status(request_id)
    finally:
        publisher.close()
    _print_operation(result, table)


@app.command("reconcile")
@command
def studio_reconcile(
    request_id: str = typer.Argument(..., help="Operation UUID to reconcile through verified Studio"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Read exact receipt post ID in verified Studio; never guess by caption."""
    publisher = StudioPublisher(get_config())
    try:
        result = publisher.reconcile(request_id)
    finally:
        publisher.close()
    _print_operation(result, table)
