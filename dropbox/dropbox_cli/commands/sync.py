"""Dropbox desktop sync inspection commands."""
from pathlib import Path

import typer

from ..output import handle_error, print_json, print_table, print_warning
from ..sync_queue import DEFAULT_DB_PATH, DEFAULT_DROPBOX_ROOT, read_pending_sync_items

COMMAND_CREDENTIALS = {
    "pending": [
        "no_auth"
    ]
}

app = typer.Typer(help="Inspect Dropbox desktop sync state")


@app.command("pending")
def sync_pending(
    db: Path = typer.Option(
        DEFAULT_DB_PATH,
        "--db",
        help="Dropbox desktop nucleus.sqlite3 path",
    ),
    dropbox_root: Path = typer.Option(
        DEFAULT_DROPBOX_ROOT,
        "--dropbox-root",
        help="Local Dropbox root for heuristic path candidates",
    ),
    resolve_paths: bool = typer.Option(
        True,
        "--resolve-paths/--no-resolve-paths",
        help="Find heuristic path candidates by exact filename under Dropbox root",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Report pending Dropbox desktop sync items from the local queue."""
    try:
        result = read_pending_sync_items(
            db_path=db,
            dropbox_root=dropbox_root,
            resolve_paths=resolve_paths,
        )
        if resolve_paths:
            print_warning(
                "Path candidates are heuristic exact filename matches under Dropbox root; "
                "the queue source of truth is commit_intents."
            )

        if table:
            rows = [
                {
                    "key": entry["queue_key_hex"],
                    "filename": entry["filename"] or "",
                    "candidate_count": len(entry["path_candidates"]),
                    "first_path": entry["path_candidates"][0] if entry["path_candidates"] else "",
                }
                for entry in result["entries"]
            ]
            print_table(
                rows,
                ["key", "filename", "candidate_count", "first_path"],
                ["Key", "Filename", "Candidates", "First Path Candidate"],
            )
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))
