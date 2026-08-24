"""`legoscout sources` -- the source registry: which marketplaces, and how."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_error, print_json

from .. import delegate, render
from ..ledger import db as ledger_db
from ..ledger import watermarks as watermarks_module
from ..sources import add_source as add_source_module
from ..sources import registry

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="The source registry: which marketplaces, and how to "
                       "reach each one", no_args_is_help=True)
notes_app = typer.Typer(help="Per-source learning notes", no_args_is_help=True)

COLUMNS = ["namespace", "short", "display_name", "status"]


def _entries():
    table = registry.sources.table()
    return [dict(entry, namespace=name) for name, entry in sorted(table.items())]


@app.command("list")
@command
def list_sources(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of sources"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every registered source."""
    render.check_filters(filter)
    rows = _entries()
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties, COLUMNS,
                "No sources registered.")


@app.command("get")
@command
def get_source(
    source: str = typer.Argument(..., help="A namespace, alias or listing_key"),
    notes: bool = typer.Option(False, "--notes", help="Include learning notes"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one source's payload."""
    try:
        entry = registry.payload(source, with_notes=notes)
    except KeyError as exc:
        print_error(str(exc))
        raise typer.Exit(2)
    render.one(entry, table, properties)


@app.command("add")
@command
def add(
    entry: Optional[str] = typer.Argument(
        None, help="Path to a filled entry JSON file (from --template)"),
    template: Optional[str] = typer.Option(
        None, "--template", help="Print a skeleton entry for this namespace and exit"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Run every validation rule and write nothing"),
):
    """Register a researched source, or print the template to research it."""
    argv = []
    if entry:
        argv.append(entry)
    delegate.flag(delegate.option(argv, "--template", template), "--dry-run", dry_run)
    delegate.run(add_source_module, argv)


@app.command("remove")
@command
def remove(
    namespace: str = typer.Argument(..., help="The namespace to retract"),
):
    """Delete a source and its notes: the reverse of `add`.

    Refuses when the ledger already holds deals on that namespace.
    """
    delegate.run(add_source_module, ["--retract", namespace])


@notes_app.command("list")
@command
def notes_list(
    source: str = typer.Argument(..., help="A namespace, alias or listing_key"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of notes"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List a source's current learning notes.

    A note another note supersedes is hidden: this is the current position, not
    the whole archaeology.
    """
    def fetch():
        return registry.current_notes(registry.sources.entry(source))

    render.check_filters(filter)
    rows = fetch()
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties,
                ["id", "date", "text", "supersedes"], "No notes recorded.")


@notes_app.command("get")
@command
def notes_get(
    note_id: str = typer.Argument(..., help="A note id, e.g. ebay-2026-08-06-1"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one learning note by its id."""
    namespace = note_id.rsplit("-", 4)[0]
    notes = registry.sources.entry(namespace)["notes"]
    render.one(next((n for n in notes if n["id"] == note_id), None), table,
               properties, "No note %r." % note_id)


@notes_app.command("add")
@command
def notes_add(
    source: str = typer.Argument(..., help="A namespace, alias or listing_key"),
    text: str = typer.Option(..., "--text", help="The note text"),
    date: Optional[str] = typer.Option(
        None, "--date", help="ISO date for the note; today when omitted"),
):
    """Append a learning note to a source."""
    when = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print_json(registry.sources.append_note(source, text, when))


@app.command("validate")
@command
def validate():
    """Report every structural problem with the registry. Exits 1 on any."""
    problems = registry.check()
    if problems:
        for problem in problems:
            print_error(problem)
        raise typer.Exit(1)
    print_json({"sources": len(registry.sources.table()), "problems": []})


@app.command("watermarks")
@command
def watermarks(
    apply: bool = typer.Option(
        False, "--apply", help="Write the computed watermarks back to the ledger"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Per-source crawl watermarks: how far back the next run must reach."""
    computed = watermarks_module.compute_watermarks(ledger_db.load_document())
    if apply:
        delegate.run(watermarks_module, ["--apply"])
        return
    rows = [dict(value, namespace=name) for name, value in sorted(computed.items())]
    render.rows(rows, table, properties,
                ["namespace", "last_listing_date", "basis", "deal_count"],
                "No watermarks computed.")


app.add_typer(notes_app, name="notes")
