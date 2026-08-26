"""`legoscout deals` -- read and repair the canonical deal ledger."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_error, print_json

from .. import delegate, render
from ..invalidate import sweep as expire_module
from ..ledger import build_record, db as ledger_db, schema as deal_schema
from ..ledger import sweep as sweep_module
from ..ledger import validate as validate_module
from ..orchestrator import (
    build_run_manifest,
    replay_fixtures,
    validate_identification_result,
)
from ..sources import listing, readers

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="The canonical deal ledger", no_args_is_help=True)

COLUMNS = ["listing_key", "source", "status", "score", "estimated_total", "title"]

# `field:op:value` translated to SQL, so `--limit` and `--filter` reach the
# database rather than slicing 2,000 rows in memory afterwards.
_SQL_OPS = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
            "like": "LIKE", "contains": "LIKE"}


def _where(filters):
    """(sql, params) for the filters SQLite can answer. Returns ("", ()) for none."""
    clauses, params = [], []
    for spec in filters or []:
        field, _, rest = spec.partition(":")
        op, _, value = rest.partition(":")
        column = "".join(ch for ch in field if ch.isalnum() or ch == "_")
        if not column or column not in ledger_db._COLUMNS or op not in _SQL_OPS:
            # Not a column, or not an operator SQLite can answer. The shared
            # in-memory filter still applies it, so nothing is dropped.
            continue
        clauses.append("%s %s ?" % (column, _SQL_OPS[op]))
        params.append("%%%s%%" % value if op == "contains" else value)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)


def _select_identification_record(batch, listing_key: str) -> dict:
    """Validate one canonical priced batch and select its unique keyed row."""
    if not isinstance(batch, list):
        raise ValueError(
            "identification JSON root must be an array, got %s"
            % type(batch).__name__)

    matches = []
    for index, record in enumerate(batch):
        if not isinstance(record, dict):
            raise ValueError(
                "identification record %d must be an object, got %s"
                % (index, type(record).__name__))
        try:
            validate_identification_result(
                record, "identification record %d" % index)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "identification record %d is malformed: %s" % (index, exc)
            ) from exc
        if record.get("listing_key") == listing_key:
            matches.append(record)

    if len(matches) != 1:
        raise ValueError(
            "identification batch must contain exactly one record matching "
            "candidate listing_key %r; found %d" % (listing_key, len(matches)))
    return matches[0]


@app.command("list")
@command
def list_deals(
    # `min=0` so Typer refuses a negative limit with a usage error. Without it
    # `--limit -1` skipped the slice entirely and returned the WHOLE ledger --
    # the opposite of what a caller asking for fewer rows meant.
    limit: int = typer.Option(100, "--limit", "-l", min=0,
                              help="Maximum number of deals"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List deals, newest score first."""
    render.check_filters(filter)
    where, params = _where(filter)
    sql = ("SELECT * FROM deals%s ORDER BY score DESC NULLS LAST, listing_key"
           % where)
    rows = ledger_db.query(sql, params)
    # SQLite answered the filters it could; the shared filter applies the rest,
    # so a filter on a JSON field or an operator SQL has no answer for is never
    # silently dropped.
    if filter:
        rows = apply_filters(rows, filter)
    rows = rows[:limit]
    render.rows(rows, table, properties, COLUMNS, "No deals found.")


@app.command("get")
@command
def get_deal(
    listing_key: str = typer.Argument(..., help="The deal's listing_key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one deal record."""
    render.one(ledger_db.get_deal(listing_key), table, properties,
               "No deal with listing_key %r." % listing_key)


@app.command("read")
@command
def read(
    listing_key: str = typer.Argument(..., help="The deal's listing_key"),
    field: str = typer.Argument(
        ..., help="A deal-record column: %s" % ", ".join(readers.FIELDS)),
    url: Optional[str] = typer.Option(
        None, "--url",
        help="The listing URL, for a candidate that has no ledger row yet"),
):
    """Read ONE field live off the listing itself, for debugging.

    This is the source reader, not the ledger: it fetches the marketplace.

    `--url` is what makes this usable on a FRESH crawl candidate. Without a
    ledger row the record carries no URL, and a reader that fetches the page
    could only answer `unknown url type: ''` -- which is exactly the moment a
    single-field debug read is worth most.
    """
    deal = ledger_db.get_deal(listing_key) or {"listing_key": listing_key}
    if url:
        deal = dict(deal, url=url, direct_url=url)
    try:
        value, evidence = readers.read(deal, field)
    except listing.Undetermined as exc:
        print_json({"listing_key": listing_key, "field": field,
                    "undetermined": str(exc), "gone": getattr(exc, "gone", False)})
        raise typer.Exit(2)
    print_json({"listing_key": listing_key, "field": field,
                "value": value, "evidence": str(evidence)})


@app.command("refresh")
@command
def refresh(
    field: Optional[str] = typer.Argument(
        None, help="The ledger field to re-read: %s" % ", ".join(sorted(sweep_module.SWEEPS))),
    apply: bool = typer.Option(False, "--apply", help="Write the answers back"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report and write nothing"),
    source: Optional[str] = typer.Option(None, "--source", help="One listing_key namespace"),
    include_inactive: bool = typer.Option(
        False, "--include-inactive", help="Do not skip dead listings"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Stop after this many rows"),
    key: Optional[List[str]] = typer.Option(
        None, "--key", help="Limit to these listing_keys (repeatable)"),
    force: bool = typer.Option(
        False, "--force", help="Re-answer rows the done-predicate would skip"),
    ledger: Optional[str] = typer.Option(None, "--ledger", help="A different ledger path"),
    set: Optional[List[str]] = typer.Option(
        None, "--set", metavar="KEY=VALUE",
        help="Write an agent-read answer for one row, through the same "
             "resolve-and-write path the readers use"),
    list: bool = typer.Option(False, "--list", help="The sweeps and what they read"),
):
    """Re-read one field across the ledger, from the listing itself."""
    argv = [field] if field else []
    delegate.flag(argv, "--apply", apply)
    delegate.flag(argv, "--dry-run", dry_run)
    delegate.option(argv, "--source", source)
    delegate.flag(argv, "--include-inactive", include_inactive)
    delegate.option(argv, "--limit", limit)
    for value in key or []:
        argv.extend(["--key", value])
    delegate.flag(argv, "--force", force)
    delegate.option(argv, "--ledger", ledger)
    for value in set or []:
        argv.extend(["--set", value])
    delegate.flag(argv, "--list", list)
    delegate.run(sweep_module, argv)


@app.command("build")
@command
def build(
    candidate: str = typer.Argument(..., help="A crawl-phase candidate JSON file"),
    appraisal: str = typer.Argument(..., help="The matching appraisal JSON file"),
    identification: Optional[str] = typer.Option(
        None, "--identification",
        help="Canonical priced minifigure identification JSON array"),
    fee_rate: Optional[float] = typer.Option(
        None, "--fee-rate",
        help="Explicit resale fee rate as a decimal; required with --identification"),
    first_seen_at: Optional[str] = typer.Option(
        None, "--first-seen-at",
        help="When this listing was first seen; now (UTC) when omitted"),
    last_seen_at: Optional[str] = typer.Option(
        None, "--last-seen-at",
        help="When this listing was last seen; now (UTC) when omitted"),
):
    """Assemble one ledger-ready record. Prints JSON; persists nothing.

    `build_deal_record` requires both timestamps and defaults NEITHER, because a
    record whose `first_seen_at` was invented is a record whose age is fiction.
    Re-assembling an existing row therefore passes its stored `--first-seen-at`;
    only a genuinely new sighting takes the clock.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if first_seen_at is None:
        first_seen_at = now
    if last_seen_at is None:
        last_seen_at = now
    with open(candidate, encoding="utf-8") as fh:
        candidate_record = json.load(fh)
    if not isinstance(candidate_record, dict):
        raise ValueError(
            "candidate JSON root must be an object, got %s"
            % type(candidate_record).__name__)
    with open(appraisal, encoding="utf-8") as fh:
        appraisal_record = json.load(fh)
    if not isinstance(appraisal_record, dict):
        raise ValueError(
            "appraisal JSON root must be an object, got %s"
            % type(appraisal_record).__name__)
    candidate_key = candidate_record.get("listing_key")
    if not isinstance(candidate_key, str) or not candidate_key.strip():
        raise ValueError(
            "candidate listing_key must be a non-empty string")
    appraisal_key = appraisal_record.get("listing_key")
    if appraisal_key is not None and appraisal_key != candidate_key:
        raise ValueError(
            "appraisal listing_key does not match candidate listing_key: "
            "%r != %r" % (appraisal_key, candidate_key))

    identification_record = None
    if identification is not None:
        if fee_rate is None:
            raise ValueError(
                "--fee-rate is required when --identification is supplied")
        if not math.isfinite(fee_rate) or not 0 <= fee_rate < 1:
            raise ValueError(
                "fee rate must be a finite decimal from 0 through less than 1")
        with open(identification, encoding="utf-8") as fh:
            identification_batch = json.load(fh)
        identification_record = _select_identification_record(
            identification_batch, candidate_key)
    elif fee_rate is not None:
        raise ValueError(
            "--identification is required when --fee-rate is supplied")

    print_json(build_record.build_deal_record(
        candidate_record, appraisal_record,
        first_seen_at=first_seen_at, last_seen_at=last_seen_at,
        identification=identification_record, fee_rate=fee_rate))


@app.command("run-manifest")
@command
def run_manifest(
    run_dir: str = typer.Argument(..., help="A source-runs directory"),
):
    """Report active-source artifacts and exact appraisal coverage."""
    manifest = build_run_manifest(run_dir)
    print_json(manifest)
    if not manifest["complete"]:
        raise typer.Exit(1)


@app.command("validate")
@command
def validate(
    file: Optional[str] = typer.Option(None, "--file", help="A different ledger path"),
    strict: bool = typer.Option(False, "--strict", help="Exit 1 if any ERROR"),
    include_inactive: bool = typer.Option(
        False, "--include-inactive", help="Check dead listings too"),
):
    """Hard gate: a deal record is invalid unless it stores a usable numeric price."""
    argv = []
    delegate.option(argv, "--file", file)
    delegate.flag(argv, "--strict", strict)
    delegate.flag(argv, "--include-inactive", include_inactive)
    delegate.run(validate_module, argv)


@app.command("status")
@command
def status(
    listing_key: str = typer.Argument(..., help="The deal's listing_key"),
    status: str = typer.Argument(
        ..., help="One of: " + " / ".join(ledger_db.SETTABLE_STATUS)),
):
    """Set one deal's status."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    changed = ledger_db.update_status(listing_key, status, now)
    if not changed:
        print_error("no deal with listing_key %r" % listing_key)
        raise typer.Exit(2)
    print_json({"listing_key": listing_key, "status": status, "updated": True})


@app.command("expire")
@command
def expire(
    apply: bool = typer.Option(
        False, "--apply",
        help="Write confirmed_unavailable/blocked rows and stamp "
             "confirmed_still_active rows, batched in one upsert_deals() call"),
    timeout_seconds: float = typer.Option(
        expire_module.DEFAULT_SWEEP_TIMEOUT_SECONDS, "--timeout-seconds",
        min=0.001, help="Hard limit for the complete sweep"),
    listing_timeout_seconds: float = typer.Option(
        expire_module.DEFAULT_LISTING_TIMEOUT_SECONDS, "--listing-timeout-seconds",
        min=0.001, help="Hard limit for one live listing check"),
):
    """Resolve every active listing to available/unavailable/blocked.

    A real, already-past auction_end_date resolves a row with no live check.
    A row with no usable date (fixed-price, or an uncaptured date) is
    live-checked through invalidate/checks.py's per-source dispatch table,
    honoring a 12-hour freshness cooldown. There is no manual-check bucket:
    every active row resolves to confirmed_unavailable, confirmed_still_active,
    check_failed, blocked, or (for an unparseable date) unreadable_end_date.
    """
    argv = delegate.flag([], "--apply", apply)
    delegate.option(argv, "--timeout-seconds", timeout_seconds)
    delegate.option(argv, "--listing-timeout-seconds", listing_timeout_seconds)
    delegate.run(expire_module, argv)


@app.command("schema")
@command
def schema(
    phase: Optional[str] = typer.Argument(
        None, help="crawl / appraisal / synthesis; every field when omitted"),
    json_out: bool = typer.Option(
        False, "--json", help="the raw JSON Schema properties, for a machine caller"),
):
    """Print the deal-record schema for one pipeline phase."""
    delegate.run(deal_schema,
                 delegate.flag([phase] if phase else [], "--json", json_out))


@app.command("replay")
@command
def replay():
    """Replay the stored source-run fixtures through build and validate."""
    delegate.run(replay_fixtures, [])
