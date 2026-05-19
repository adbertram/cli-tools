"""Job commands."""
from typing import List, Optional

import typer

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_download, output_item, output_list


COMMAND_CREDENTIALS = {"history": ["custom"], "status": ["custom"], "download": ["custom"], "replay": ["custom"]}

app = typer.Typer(help="Manage async export jobs", no_args_is_help=True)


@app.command("history")
def jobs_history(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List jobs."""
    try:
        output_list(get_client().list_jobs(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("status")
def jobs_status(job_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get job status."""
    try:
        output_item(get_client().get_job(job_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("download")
def jobs_download(job_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Download job result content."""
    try:
        output_download(get_client().download_job(job_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("replay")
def jobs_replay(
    job_id: str,
    force: bool = typer.Option(False, "--force", "-F", help="Replay the job"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Replay a job."""
    try:
        if not force:
            raise ClientError("Replay mutates server state; rerun with --force to continue")
        output_item(get_client().replay_job(job_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
