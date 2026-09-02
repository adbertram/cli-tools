"""Main entry point for the Microworker CLI.

Commands: `discover`, `merge`, `validate`, and the `sites`, `tasks` and `runs`
groups. `discover` writes one site envelope; `merge` folds a run's envelopes
into the SQLite store; `tasks` and `runs` read that store back.

Every `list` command carries `--table/-t`, `--filter/-f`, `--limit/-l` and
`--properties/-p`; every `get` command carries `--table/-t` and
`--properties/-p`. `_emit_rows` and `_emit_row` own that shared tail so the
option handling cannot drift between the six of them.

FIELD NAMES ARE CHECKED AGAINST THE REAL COLUMNS. Each command declares the
fields its rows actually carry, and the shared tail rejects any `--filter` or
`--properties` naming something else. Without that, both options fail silently
in opposite directions: a misspelled filter field matches nothing and returns
`[]` with exit 0, so "that field does not exist" is indistinguishable from "no
task matched"; and a misspelled property is emitted as a `null` on every row, so
a typo reads as "the field exists and is empty".

TRUNCATION IS ANNOUNCED. `--limit` defaults to 100, and a ledger with more rows
than that would otherwise return exactly 100 with nothing anywhere saying so.
When the limit cuts the result, the pre-limit total goes to STDERR -- stdout
stays data only, so piping into `jq` is unaffected.
"""

from __future__ import annotations

import dataclasses
import functools
from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.exceptions import ClientError, ConfigError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_limit,
    apply_properties_filter,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import (
    __version__,
    db,
    discover as discover_module,
    merge as merge_module,
    schema,
    sites,
)

app = create_app(
    name="microworker",
    help="Runs the per-site gig CLIs for the MicroWorker project, writes site "
         "envelopes, and merges them into one durable task database",
    version=__version__,
    cache_support=False,
)
sites_app = typer.Typer(help="Sites registered in the project's config.json",
                        no_args_is_help=True)
tasks_app = typer.Typer(help="Tasks merged into the task database",
                        no_args_is_help=True)
runs_app = typer.Typer(help="Merges recorded in the task database",
                       no_args_is_help=True)

# The exact fields each command's rows carry, used as the allowlist for
# `--filter` and `--properties`. They are derived from the row builders --
# `sites.SiteConfig` and the database's own column tuples -- so a schema change
# cannot leave the allowlist behind. `runs get` adds `sites`, the per-site
# summary object it alone returns.
SITE_FIELDS = tuple(field.name for field in dataclasses.fields(sites.SiteConfig))
TASK_FIELDS = db.TASK_COLUMNS
RUN_FIELDS = db.RUN_COLUMNS
RUN_GET_FIELDS = RUN_FIELDS + ("sites",)


def exit_2_on_contract_errors(fn):
    """Config and schema/contract errors are exit 2, not the generic 1.

    The shared `@command` decorator maps everything but `CredentialError` to
    exit 1; this sits beneath it so `ClientError` and `ConfigError` reach the
    documented exit code instead. `FilterValidationError` joins them: a
    malformed `--filter`, or one naming a field these rows do not have, is the
    caller's input being wrong -- the same class of failure as a bad
    `--properties`, which raises `ClientError` -- not an unexpected error.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ClientError, ConfigError, FilterValidationError) as exc:
            print_error(str(exc))
            raise typer.Exit(2)
    return wrapper


def _check_properties(properties, fields):
    """Reject a `--properties` name that is not a real field.

    Only the first dotted segment is checked: the top-level names are this
    command's fixed columns, while anything below one (a `runs get` row's
    `sites.<site>`) is data whose keys are not knowable here.
    """
    if not properties:
        return
    named = {part.strip().split(".")[0]
             for part in properties.split(",") if part.strip()}
    unknown = sorted(named - set(fields))
    if unknown:
        raise ClientError(
            f"--properties names no such field: {', '.join(unknown)}; "
            f"available fields: {', '.join(fields)}")


def _emit_rows(rows, *, filter, limit, properties, table, empty, noun,
               fields, drop=()):
    """The shared `list` tail: filter, limit, properties, then JSON or a table.

    `fields` is the exact set of columns these rows carry; it is the allowlist
    for both `--filter` and `--properties`, so a typo in either is an exit-2
    error naming the real fields instead of a silently empty or null-filled
    result.

    `drop` names columns a table cannot usefully show -- a task's `raw` site
    record is a whole nested object -- and applies to table output only, so the
    JSON form stays complete.
    """
    _check_properties(properties, fields)
    if filter:
        rows = apply_filters(rows, filter, allowed_fields=fields)
    total = len(rows)
    rows = apply_limit(rows, limit)
    if len(rows) < total:
        print_info(
            f"Showing {len(rows)} of {total} {noun} (--limit {limit}); "
            "raise --limit for the rest.")
    rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    rows = [{key: value for key, value in row.items() if key not in drop}
            for row in rows]
    columns = list(rows[0])
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _emit_row(row, *, properties, table, fields):
    """The shared `get` tail: properties, then JSON or a field/value table."""
    _check_properties(properties, fields)
    row = apply_properties_filter([row], properties)[0]
    if not table:
        print_json(row)
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


@app.command("discover")
@command
@exit_2_on_contract_errors
def discover(
    site: str = typer.Argument(..., help="Site name from config.json"),
    run_id: str = typer.Option(..., "--run-id", help="Discovery run identifier; the envelope lands under agent_workspaces/discovery/<run_id>/"),
    timeout: int = typer.Option(300, "--timeout", help="Seconds allowed for each site CLI command"),
):
    """Run one site's CLI and write its envelope for this run."""
    print_json(discover_module.discover(site, run_id, timeout))


@app.command("merge")
@command
@exit_2_on_contract_errors
def merge(
    run_id: str = typer.Argument(..., help="Discovery run identifier whose envelopes to merge"),
):
    """Merge every site envelope of a run into the task database."""
    print_json(merge_module.merge(run_id))


@app.command("validate")
@command
@exit_2_on_contract_errors
def validate(
    file: Path = typer.Argument(..., help="A site envelope file to validate"),
):
    """Validate a site envelope against its schema."""
    kind = schema.validate_file(file)
    print_json({"file": str(file), "kind": kind, "valid": True})


@sites_app.command("list")
@command
@exit_2_on_contract_errors
def sites_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of sites"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List the sites in config.json."""
    rows = [sites.site_row(site) for site in sites.load_sites().values()]
    _emit_rows(rows, filter=filter, limit=limit, properties=properties,
               table=table, empty="No sites found.", noun="sites",
               fields=SITE_FIELDS)


@sites_app.command("get")
@command
@exit_2_on_contract_errors
def sites_get(
    name: str = typer.Argument(..., help="Site name from config.json"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one site's config.json entry."""
    _emit_row(sites.site_row(sites.get_site(name)), properties=properties,
              table=table, fields=SITE_FIELDS)


@tasks_app.command("list")
@command
@exit_2_on_contract_errors
def tasks_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of tasks"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List merged tasks, most recently seen first."""
    _emit_rows(db.list_tasks(), filter=filter, limit=limit, properties=properties,
               table=table, empty="No tasks found.", noun="tasks",
               fields=TASK_FIELDS, drop=("raw",))


@tasks_app.command("get")
@command
@exit_2_on_contract_errors
def tasks_get(
    site: str = typer.Argument(..., help="Site the task belongs to"),
    task_id: str = typer.Argument(..., help="Task identifier within that site"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one merged task by site and task id."""
    _emit_row(db.get_task(site, task_id), properties=properties, table=table,
              fields=TASK_FIELDS)


@runs_app.command("list")
@command
@exit_2_on_contract_errors
def runs_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of runs"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List recorded merges, most recent first."""
    _emit_rows(db.list_runs(), filter=filter, limit=limit, properties=properties,
               table=table, empty="No runs found.", noun="runs",
               fields=RUN_FIELDS)


@runs_app.command("get")
@command
@exit_2_on_contract_errors
def runs_get(
    run_id: str = typer.Argument(..., help="Discovery run identifier"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one merge with its per-site summaries."""
    _emit_row(db.get_run(run_id), properties=properties, table=table,
              fields=RUN_GET_FIELDS)


app.add_typer(sites_app, name="sites")
app.add_typer(tasks_app, name="tasks")
app.add_typer(runs_app, name="runs")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
