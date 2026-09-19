"""Operator maintenance: rerender, retention sweeps, imports, demo data."""

COMMAND_CREDENTIALS = {
    "status": ["browser_session"],
    "rerender": ["no_auth"],
    "ip-retention": ["no_auth"],
    "audit-retention": ["no_auth"],
    "import": ["no_auth"],
    "seed-demo": ["no_auth"],
}

from pathlib import Path
from typing import Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, print_json

from ..client import IMPORT_SOURCES, get_client
from ..helpers import mutate

app = typer.Typer(help="Run operator maintenance jobs", no_args_is_help=True)


@app.command("status")
@command
def ops_status():
    """Show rerender backlog and the state of both retention sweeps."""
    print_json(get_client().get_operator_status())


@app.command("rerender")
@command
def rerender(
    batch: int = typer.Option(50, "--batch", help="Comments to rerender in this call, 1 to 100"),
    cursor_created_at: Optional[int] = typer.Option(None, "--cursor-created-at", help="next_cursor.created_at from the previous call"),
    cursor_id: Optional[str] = typer.Option(None, "--cursor-id", help="next_cursor.id from the previous call"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Run the batch"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Re-render one batch of comments stored under an older markdown renderer."""
    if not 1 <= batch <= 100:
        raise ClientError("--batch must be between 1 and 100.")
    if (cursor_created_at is None) != (cursor_id is None):
        raise ClientError("Pass --cursor-created-at and --cursor-id together, or neither.")
    cursor = None if cursor_id is None else {"created_at": cursor_created_at, "id": cursor_id}
    mutate(
        f"rerender up to {batch} comments",
        {"method": "POST", "path": "/admin/api/ops/rerender", "body": {"batch": batch, "cursor": cursor}},
        yes,
        dry_run,
        lambda: get_client().rerender(batch, cursor),
    )


@app.command("ip-retention")
@command
def ip_retention(
    yes: bool = typer.Option(False, "--yes", "-y", help="Destroy the expired hashes. This cannot be undone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Irreversibly clear one batch of stored IP hashes older than the configured window."""
    mutate(
        "clear expired IP hashes",
        {"method": "POST", "path": "/admin/api/ops/ip-retention", "body": {}},
        yes,
        dry_run,
        lambda: get_client().sweep_ip_retention(),
    )


@app.command("audit-retention")
@command
def audit_retention(
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete the expired rows. This cannot be undone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Irreversibly delete one batch of audit rows older than the configured window."""
    mutate(
        "delete expired audit rows",
        {"method": "POST", "path": "/admin/api/ops/audit-retention", "body": {}},
        yes,
        dry_run,
        lambda: get_client().sweep_audit_retention(),
    )


@app.command("import")
@command
def import_comments(
    source: str = typer.Argument(..., help="disqus, remark42, comentario, isso or cusdis"),
    file: Path = typer.Argument(..., help="Export file, gzipped or not"),
    plan: bool = typer.Option(False, "--plan", help="Ask Garrul for the import plan only. Nothing is inserted"),
    include_deleted: bool = typer.Option(False, "--include-deleted", help="Also import deleted comments"),
    include_spam: bool = typer.Option(False, "--include-spam", help="Also import spam comments"),
    domain: Optional[str] = typer.Option(None, "--domain", help="Comentario domain or Cusdis project id to import"),
    site: Optional[str] = typer.Option(None, "--site", help="Site origin for isso and Cusdis page paths"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Send the file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Import comments from another comment system. Re-uploading the same file inserts nothing new."""
    if source not in IMPORT_SOURCES:
        raise ClientError(f"Unknown import source {source!r}. Valid sources: {', '.join(IMPORT_SOURCES)}.")
    if not file.is_file():
        raise ClientError(f"Import file {file} is not a readable file.")
    headers = {"Content-Type": "application/octet-stream"}
    for name, enabled in (("x-dry-run", plan), ("x-include-deleted", include_deleted), ("x-include-spam", include_spam)):
        if enabled:
            headers[name] = "1"
    for name, value in (("x-import-domain", domain), ("x-import-site", site)):
        if value is not None:
            headers[name] = value
    mutate(
        f"{'plan' if plan else 'run'} a {source} import of {file.name}",
        {"method": "POST", "path": f"/admin/api/ops/import-{source}", "headers": headers, "file": str(file), "bytes": file.stat().st_size},
        yes,
        dry_run,
        lambda: get_client().import_comments(source, file, headers),
    )


@app.command("seed-demo")
@command
def seed_demo(
    yes: bool = typer.Option(False, "--yes", "-y", help="Insert the demo post and comments"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Insert the demo `welcome` thread. Garrul refuses this unless the instance runs with ENV=dev."""
    mutate(
        "seed demo content",
        {"method": "POST", "path": "/admin/api/ops/seed-demo", "body": {}},
        yes,
        dry_run,
        lambda: get_client().seed_demo(),
    )
