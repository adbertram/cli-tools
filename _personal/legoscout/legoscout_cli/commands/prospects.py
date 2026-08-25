"""`legoscout prospects` -- new inventory sources, contacts, outreach and runs."""
from __future__ import annotations

import json
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_error, print_json

from .. import delegate, render
from ..ledger import outreach as outreach_module
from ..ledger import prospects as prospects_db
from ..prospector import hypothesis_types

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="Prospecting: new inventory sources and their contacts",
                  no_args_is_help=True)
contacts_app = typer.Typer(help="Contacts on a prospect", no_args_is_help=True)
outreach_app = typer.Typer(help="Outreach to a prospect", no_args_is_help=True)
runs_app = typer.Typer(help="Prospecting runs", no_args_is_help=True)
hypotheses_app = typer.Typer(help="Registered prospecting hypothesis types",
                             no_args_is_help=True)

# The `--table` column sets. Each one names REAL columns of its own table, and
# each identity column comes from prospects_db.PRIMARY_KEYS rather than a bare
# `id`, which no prospect table has.
# `tests/test_prospect_schema_contract.py` asserts every name here against
# PRAGMA table_info, because a column the table does not have renders as a
# silently empty cell instead of an error.
PROSPECT_COLUMNS = [prospects_db.PRIMARY_KEYS["prospects"],
                    "name", "hypothesis_type", "status", "location"]
CONTACT_COLUMNS = [prospects_db.PRIMARY_KEYS["contacts"],
                   "prospect_id", "person_name", "email", "phone"]
OUTREACH_COLUMNS = [prospects_db.PRIMARY_KEYS["outreach"],
                    "prospect_id", "contact_id", "state", "outcome"]
RUN_COLUMNS = [prospects_db.PRIMARY_KEYS["prospect_runs"],
               "run_key", "hypothesis_type", "result_count", "recorded_at"]
# The registry is JSON, not a table, but the same rule holds: every name here is
# a key `hypothesis_types.table()` entries actually carry. `label` and `scope`
# were neither, so this set rendered three columns and filled one. `description`
# and `rationale` are paragraphs, so they stay out of the default table and are
# reachable through `--properties`; the JSON output already carries every key.
HYPOTHESIS_COLUMNS = ["hypothesis_type", "evidence", "verified_at"]


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@app.command("list")
@command
def list_prospects(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of prospects"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every recorded prospect."""
    render.check_filters(filter)
    rows = prospects_db.list_prospects()
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties, PROSPECT_COLUMNS,
                "No prospects recorded.")


@app.command("get")
@command
def get_prospect(
    prospect_id: str = typer.Argument(..., help="The prospect's id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one prospect, with its contacts and outreach."""
    render.one(prospects_db.get_prospect(prospect_id), table, properties,
               "No prospect %r." % prospect_id)


@app.command("create")
@command
def create_prospect(
    record: str = typer.Argument(..., help="A prospect JSON file"),
):
    """Record one evidence-backed prospect."""
    print_json(prospects_db.insert_prospect(_load(record)))


@contacts_app.command("list")
@command
def contacts_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of contacts"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every recorded contact."""
    render.check_filters(filter)
    rows = prospects_db.list_contacts()
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties, CONTACT_COLUMNS,
                "No contacts recorded.")


@contacts_app.command("get")
@command
def contacts_get(
    contact_id: str = typer.Argument(..., help="The contact's id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one contact row."""
    render.one(prospects_db.contact_row(contact_id), table, properties,
               "No contact %r." % contact_id)


@contacts_app.command("create")
@command
def contacts_create(
    record: str = typer.Argument(..., help="A contact JSON file"),
):
    """Record one contact on a prospect."""
    print_json(prospects_db.insert_contact(_load(record)))


@outreach_app.command("list")
@command
def outreach_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of rows"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every outreach row and its state."""
    render.check_filters(filter)
    rows = prospects_db.list_outreach()
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties, OUTREACH_COLUMNS,
                "No outreach recorded.")


@outreach_app.command("get")
@command
def outreach_get(
    outreach_id: str = typer.Argument(..., help="The outreach row's id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one outreach row and its state."""
    render.one(prospects_db.outreach_row(outreach_id), table, properties,
               "No outreach %r." % outreach_id)


@outreach_app.command("send")
@command
def outreach_send(
    outreach_id: str = typer.Argument(..., help="The outreach row to send"),
    confirm: bool = typer.Option(
        False, "--confirm", help="Adam approved THIS exact body; send it"),
    db: Optional[str] = typer.Option(None, "--db", help="A different ledger path"),
):
    """Send one approved outreach email.

    Without `--confirm` this previews and sends nothing. LegoScout never
    contacts anyone without Adam's explicit per-action approval.
    """
    argv = [outreach_id]
    delegate.flag(argv, "--confirm", confirm)
    delegate.option(argv, "--db", db)
    delegate.run(outreach_module, argv)


@runs_app.command("list")
@command
def runs_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of runs"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every prospecting run."""
    render.check_filters(filter)
    rows = prospects_db.list_runs()
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties, RUN_COLUMNS,
                "No prospecting runs recorded.")


@runs_app.command("get")
@command
def runs_get(
    run_id: str = typer.Argument(..., help="The run's id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one prospecting run."""
    render.one(prospects_db.run_row(run_id), table, properties,
               "No run %r." % run_id)


@runs_app.command("create")
@command
def runs_create(
    record: str = typer.Argument(..., help="A run JSON file"),
):
    """Record one prospecting run."""
    print_json(prospects_db.record_run(_load(record)))


@hypotheses_app.command("list")
@command
def hypotheses_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of types"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every registered hypothesis type.

    An unregistered type cannot be stored: this registry is the gate.
    """
    def fetch():
        return [dict(entry, hypothesis_type=name)
                for name, entry in sorted(hypothesis_types.table().items())]

    render.check_filters(filter)
    rows = fetch()
    if filter:
        rows = apply_filters(rows, filter)
    render.rows(render.capped(rows, limit), table, properties,
                HYPOTHESIS_COLUMNS, "No types registered.")


@hypotheses_app.command("get")
@command
def hypotheses_get(
    hypothesis_type: str = typer.Argument(..., help="A registered type key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one registered hypothesis type."""
    try:
        entry = hypothesis_types.entry(hypothesis_type)
    except (KeyError, ValueError) as exc:
        print_error(str(exc))
        raise typer.Exit(2)
    render.one(entry, table, properties)


app.add_typer(contacts_app, name="contacts")
app.add_typer(outreach_app, name="outreach")
app.add_typer(runs_app, name="runs")
app.add_typer(hypotheses_app, name="hypotheses")
