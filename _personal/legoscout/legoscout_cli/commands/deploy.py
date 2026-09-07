"""Independent code deployment and server-authoritative observation ingestion."""
from __future__ import annotations

import json
from pathlib import Path

import typer
from cli_tools_shared.output import command, print_json

from ..deploy import availability, db_sync, release, source_notes
from ..ledger import ingestion

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="Sync the ledger and app code to adam-server", no_args_is_help=True)


@app.command("source-note")
@command
def source_note(
    source: str = typer.Argument(..., help="A namespace, alias or listing_key"),
    text: str = typer.Option(..., "--text", help="The source learning to append"),
    date: str | None = typer.Option(None, "--date", help="ISO date; today in UTC when omitted"),
):
    """Append a source learning on the authoritative server, preserving run baselines."""
    print_json(source_notes.add(source, text, date))


@app.command("expire")
@command
def expire():
    """Verify and expire active listings on the authoritative server before a run."""
    print_json(availability.expire())


@app.command("pull-db")
@command
def pull_db(output: str = typer.Option(..., "--output", help="New immutable baseline DB path; must not exist")):
    """Pull a new server baseline and merge shared crops additively."""
    report = db_sync.pull(output)
    print_json(report)
    if not report["ok"]:
        raise typer.Exit(1)


@app.command("push")
@command
def push():
    """Deploy application code; never upload a ledger or change its data."""
    try:
        result = release.deploy_code()
    except Exception as exc:
        print_json(
            {
                "ok": False,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "code_deployed": False,
            }
        )
        raise typer.Exit(1) from exc
    print_json(
        {
            "ok": True,
            "code_deployed": not result.skipped,
            "release_name": result.release_name,
        }
    )


@app.command("prepare-ingest")
@command
def prepare_ingest(
    run_id: str = typer.Option(..., "--run-id", help="Unique immutable run ID"),
    baseline: str = typer.Option(..., "--baseline", help="Immutable DB from pull-db"),
    records: str = typer.Option(..., "--records", help="JSON array of explicit newly observed deal records"),
    output: str = typer.Option(..., "--output", help="New ingestion payload file; must not exist"),
):
    """Bind explicit observations to their server baseline for conflict detection."""
    payload = ingestion.prepare(run_id, baseline, json.loads(Path(records).read_text(encoding="utf-8")))
    with open(output, "x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print_json({"run_id": run_id, "observations": len(payload["observations"]), "path": str(Path(output).resolve())})


@app.command("ingest")
@command
def ingest(payload: str = typer.Argument(..., help="Payload created by prepare-ingest")):
    """Publish a keyed observation batch transactionally on adam-server."""
    report = db_sync.ingest(payload)
    print_json(report)
    if not report["ok"]:
        raise typer.Exit(1)


@app.command("status")
@command
def status():
    """Whether adam-server's code is in sync, release list, pm2 status."""
    print_json(release.status())


@app.command("rollback")
@command
def rollback(
    target: str = typer.Argument(
        "1", help="Releases to go back (a number) or an explicit release directory name"
    ),
):
    """Roll adam-server back to an earlier release and restart it."""
    target_name = release.rollback(target)
    print_json({"ok": True, "release_name": target_name})
