"""Internal moderator notes on comments and users."""

COMMAND_CREDENTIALS = {"create": ["no_auth"], "delete": ["no_auth"]}

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command

from ..client import get_client, segment
from ..helpers import mutate

app = typer.Typer(help="Write and remove internal moderator notes", no_args_is_help=True)


@app.command("create")
@command
def create_note(
    target_kind: str = typer.Argument(..., help="comment or user"),
    target_id: str = typer.Argument(..., help="Id of the comment or user the note is about"),
    body: str = typer.Option(..., "--body", "-b", help="Plain-text note, visible to moderators only"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Save the note"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Attach a note to a comment or a user. Read notes with `comments get` or `users get`."""
    if target_kind not in ("comment", "user"):
        raise ClientError(f"Invalid target kind {target_kind!r}. Valid values: comment, user.")
    payload = {"target_kind": target_kind, "target_id": target_id, "body": body}
    mutate(
        f"add a note to {target_kind} {target_id}",
        {"method": "POST", "path": "/admin/api/notes", "body": payload},
        yes,
        dry_run,
        lambda: get_client().create_note(target_kind, target_id, body),
    )


@app.command("delete")
@command
def delete_note(
    note_id: str = typer.Argument(..., help="Note id, from the notes list in `comments get` or `users get`"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete the note. This cannot be undone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Permanently delete a note."""
    mutate(
        f"delete note {note_id}",
        {"method": "DELETE", "path": f"/admin/api/notes/{segment(note_id)}"},
        yes,
        dry_run,
        lambda: get_client().delete_note(note_id),
    )
