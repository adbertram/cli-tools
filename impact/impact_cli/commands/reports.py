"""Report commands."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, output_list, read_json_body


COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"], "run": ["custom"], "metadata": ["custom"], "export": ["custom"]}

app = typer.Typer(help="Run and export reports", no_args_is_help=True)


@app.command("list")
def reports_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List reports."""
    try:
        output_list(get_client().list_reports(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])

    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def reports_get(report_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get report metadata."""
    try:
        output_item(get_client().get_report_metadata(report_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("run")
def reports_run(
    report_id: str,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Run a report."""
    try:
        output_list(get_client().run_report(report_id, limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("metadata")
def reports_metadata(report_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get report metadata."""
    try:
        output_item(get_client().get_report_metadata(report_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("export")
def reports_export(
    report_id: str,
    json_file: Optional[str] = typer.Option(None, "--json-file", help="JSON query parameter file; stdin when omitted"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Export a report."""
    try:
        params = read_json_body(json_file) if json_file else None
        output_item(get_client().export_report(report_id, params), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
