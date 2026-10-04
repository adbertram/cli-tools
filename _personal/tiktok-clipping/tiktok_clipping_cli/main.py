"""JSON-first durable clipping coordinator command contract."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_error, print_json, print_table

from . import __version__
from .engine import AdapterFailure, Engine
from .safety import SafetyError, strict_json

app = create_app(name="tiktok-clipping", help="Durable clipping jobs, bounded model proposals, verified publication and rewards.", version=__version__, cache_support=False)
jobs = typer.Typer(help="Prepare, validate and execute durable jobs.", no_args_is_help=True)
status_app = typer.Typer(help="Inspect current setup and durable budgets.", no_args_is_help=True)
control_app = typer.Typer(help="Persist pause, stop or running state.", no_args_is_help=True)
strategy = typer.Typer(help="Bounded strategy versions and rollback.", no_args_is_help=True)
metrics = typer.Typer(help="Record provenance-preserving measurement snapshots.", no_args_is_help=True)
rewards = typer.Typer(help="Track campaign submission separately from publication and earnings.", no_args_is_help=True)
ConfigPath = Annotated[Path, typer.Option("--config", exists=True, file_okay=True, dir_okay=False, help="Trusted absolute JSON configuration file.")]


def _perform(action):
    result = action()
    print_json(result)
    return result


def _engine(config):
    return Engine.from_path(config)


def _native_engine(config, execution_id, workflow_id, *, completed=False):
    if (execution_id is None) != (workflow_id is None):
        raise SafetyError("native_execution_context_incomplete")
    native = None if execution_id is None else {"execution_id": execution_id, "workflow_id": workflow_id}
    return Engine.from_path(config, native_execution=native, native_completion=completed)


def _stdin(engine):
    maximum = engine.config["limits"]["max_payload_bytes"]
    return strict_json(sys.stdin.buffer.read(maximum + 1), maximum)


@jobs.command("prepare")
@command
def prepare(config: ConfigPath, kind: str = typer.Option(..., "--kind", help="clip, learn or metrics; metrics never enters model node."),
            execution_id: Optional[str] = typer.Option(None,"--n8n-execution-id",help="Trusted enclosing native workflow execution ID."),
            workflow_id: Optional[str] = typer.Option(None,"--n8n-workflow-id",help="Trusted configured native workflow ID."),
            native_text: bool = typer.Option(False,"--native-text",help="Require configured native text receipts; never issue legacy proposals.")):
    """Claim one durable job or return an explicit paused/unconfigured/idle state."""
    def action():
        engine = _native_engine(config,execution_id,workflow_id)
        try:
            return engine.prepare(kind,require_native_text=native_text)
        except SafetyError as exc:
            daily = {"budget_exhausted: "+field:field for field in ('posts','model_calls','runtime_seconds')}
            if str(exc) not in daily:
                raise
            health = engine.status()['health']
            return {'ready':False,'state':'waiting','reason':'daily_budget_exhausted',
                    'budget':daily[str(exc)],'retry_at':health['budget_window']['reset_at']}
    _perform(action)


@jobs.command("apply")
@command
def apply(config: ConfigPath, execution_id: Optional[str] = typer.Option(None,"--n8n-execution-id",help="Trusted enclosing native execution ID."),
          workflow_id: Optional[str] = typer.Option(None,"--n8n-workflow-id",help="Trusted configured native workflow ID.")):
    """Validate leased model JSON from stdin, then execute once through trusted adapters."""
    def action():
        engine = _native_engine(config,execution_id,workflow_id)
        return engine.apply(_stdin(engine))
    _perform(action)


@jobs.command("apply-text")
@command
def apply_text(config: ConfigPath, execution_id: str = typer.Option(...,"--n8n-execution-id",help="Original native execution ID after node return."),
               workflow_id: str = typer.Option(...,"--n8n-workflow-id",help="Original configured clip or learn workflow ID."),
               no_execute: bool = typer.Option(False,"--no-execute",help="Validate/account only; leave accepted work ready without adapter actions.")):
    """Account native receipt from stdin, then recheck its original lease before acting."""
    def action():
        engine = _native_engine(config,execution_id,workflow_id,completed=True)
        return engine.consume_text(_stdin(engine),execute=not no_execute)
    _perform(action)


@jobs.command("retry-text")
@command
def retry_text(job_id: str = typer.Argument(...,help="Blocked text job whose prerequisite has recovered."), config: ConfigPath = ...):
    """Revalidate blocked preproposal text work after its original native process ended."""
    _perform(lambda: _engine(config).retry_text(job_id))


@jobs.command("ingest")
@command
def ingest(config: ConfigPath):
    """Queue an allowlisted trusted source record from bounded JSON stdin."""
    def action():
        engine = _engine(config)
        return engine.ingest(_stdin(engine))
    _perform(action)


@jobs.command("apply-visual")
@command
def apply_visual(config: ConfigPath, execution_id: str = typer.Option(...,"--n8n-execution-id",help="Trusted enclosing native execution ID after node return."),
                 workflow_id: str = typer.Option(...,"--n8n-workflow-id",help="Trusted configured native workflow ID.")):
    """Validate a native image-review receipt and its exact durable lease."""
    def action():
        engine = _native_engine(config,execution_id,workflow_id,completed=True)
        return engine.apply_visual(_stdin(engine))
    _perform(action)


@jobs.command("run")
@command
def run(job_id: str = typer.Argument(..., help="Durable job ID."), config: ConfigPath = ...,
        execution_id: Optional[str] = typer.Option(None,"--n8n-execution-id",help="Trusted enclosing native execution ID."),
        workflow_id: Optional[str] = typer.Option(None,"--n8n-workflow-id",help="Trusted configured native workflow ID.")):
    """Run a ready job; coordinator alone owns retries and side-effect budgets."""
    _perform(lambda: _native_engine(config,execution_id,workflow_id).run(job_id))


@jobs.command("reconcile")
@command
def reconcile(job_id: str = typer.Argument(..., help="Ambiguous job ID."), config: ConfigPath = ...):
    """Read back an ambiguous upload without repeating publication."""
    _perform(lambda: _engine(config).reconcile(job_id))


@jobs.command("retry")
@command
def retry(job_id: str = typer.Argument(..., help="Blocked or proven pre-publication visual job ID."), config: ConfigPath = ...):
    """Revalidate blocked work or an explicitly proven pre-publication visual failure."""
    _perform(lambda: _engine(config).retry(job_id))


@jobs.command("maintain")
@command
def maintain(config: ConfigPath):
    """Recover expired leases, reconcile uploads and maintain campaign submissions."""
    _perform(lambda: _engine(config).maintain())


@jobs.command("list")
@command
def list_jobs(config: ConfigPath, limit: int = typer.Option(100, "--limit", "-l", min=1, max=10000, help="Maximum job records."),
              filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter field:op:value."),
              table: bool = typer.Option(False, "--table", "-t", help="Display job records as table."),
              properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields.")):
    """List durable jobs, including explicit failed, blocked and ambiguous states."""
    try:
        validate_filters(filter or [])
        rows = _engine(config).list(10000 if filter else limit)
        if filter:
            rows = apply_filters(rows, filter)[:limit]
        if properties:
            rows = apply_properties_filter(rows, properties)
        if table:
            columns = properties.split(",") if properties else ["id", "kind", "status", "stage", "attempts", "error"]
            print_table(rows, columns, columns)
        else:
            print_json(rows)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc


@jobs.command("get")
@command
def get_job(job_id: str = typer.Argument(..., help="Durable job ID."), config: ConfigPath = ...,
            table: bool = typer.Option(False, "--table", "-t", help="Display record fields as table.")):
    """Get one durable job, excluding its ownership credential."""
    if table:
        try:
            row = _engine(config).get(job_id)
            print_table([{"field": k, "value": str(v)} for k, v in row.items()], ["field", "value"], ["Field", "Value"])
        except (ValueError, OSError, sqlite3.Error) as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc
    else:
        _perform(lambda: _engine(config).get(job_id))


@status_app.command("get")
@command
def status(config: Optional[Path] = typer.Option(None, "--config", exists=True, dir_okay=False, help="Trusted JSON configuration; absent means unconfigured."),
           table: bool = typer.Option(False, "--table", "-t", help="Display aggregate state fields as table.")):
    """Inspect setup, control, account, durable budgets and strategy version."""
    action = lambda: {"state": "unconfigured", "reason": "configuration_missing"} if config is None else _engine(config).status()
    if table:
        try:
            row = action()
            print_table([{"field": k, "value": str(v)} for k, v in row.items()], ["field", "value"], ["Field", "Value"])
        except (ValueError, OSError, sqlite3.Error) as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc
    else:
        _perform(action)


@control_app.command("set")
@command
def control(state: str = typer.Argument(..., help="running, paused or stopped."), config: ConfigPath = ...):
    """Persist control state; running requires verified exact account and approved sources."""
    _perform(lambda: _engine(config).control(state))


@strategy.command("rollback")
@command
def rollback(config: ConfigPath):
    """Restore recorded baseline; models cannot change hard policy."""
    _perform(lambda: _engine(config).rollback())


@metrics.command("record")
@command
def record(config: ConfigPath):
    """Append a trusted timestamped metric snapshot from stdin; unknown values stay null."""
    def action():
        engine = _engine(config)
        return engine.snapshot(_stdin(engine))
    _perform(action)


@rewards.command("submit")
@command
def submit(job_id: str = typer.Argument(..., help="Verified publication job ID."), config: ConfigPath = ...):
    """Submit one post to its verified campaign before its verified campaign-specific deadline."""
    _perform(lambda: _engine(config).submit_rewards(job_id))


@rewards.command("refresh")
@command
def refresh(job_id: str = typer.Argument(..., help="Publication job ID."), config: ConfigPath = ...):
    """Read actual campaign acceptance/rejection and observed earnings."""
    _perform(lambda: _engine(config).reward_status(job_id))


for name, group in (("jobs", jobs), ("status", status_app), ("control", control_app), ("strategy", strategy), ("metrics", metrics), ("rewards", rewards)):
    app.add_typer(group, name=name)


def main():
    """Console entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
