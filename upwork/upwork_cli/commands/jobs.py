"""Job search commands for the Upwork CLI (official GraphQL API)."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.filters import FilterValidationError
from cli_tools_shared.output import command, handle_error

from ..jobs_client import get_jobs_client
from ._render import render_list, render_record

COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
}

JOB_COLUMNS = [
    "id",
    "title",
    "job_type",
    "experience_level",
    "published_datetime",
    "totalApplicants",
]

app = typer.Typer(help="Search Upwork marketplace job postings", no_args_is_help=True)


@app.command("list")
@command
def jobs_list(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of jobs to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help=(
            "Filter: field:op:value. Fields: query, skills, category, "
            "client_location, job_type (hourly|fixed), experience_level "
            "(entry|intermediate|expert), fixed_min, fixed_max, hourly_min, "
            "hourly_max, posted_after. Example: skills:eq:python|automation, "
            "hourly_min:gte:50, job_type:eq:hourly."
        ),
    ),
    sort: Optional[str] = typer.Option(
        None,
        "--sort",
        help="Sort order: recency or relevance",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
):
    """Search marketplace job postings via the Upwork GraphQL API."""
    client = get_jobs_client()
    try:
        rows = client.search_jobs(filters=filter, sort=sort, limit=limit)
    except FilterValidationError as exc:
        raise typer.Exit(handle_error(exc))
    render_list(
        rows,
        table=table,
        properties=properties,
        default_columns=JOB_COLUMNS,
        empty="No jobs found.",
    )


@app.command("get")
@command
def jobs_get(
    job_id: str = typer.Argument(..., help="Job posting id or ciphertext (~0abc...)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
):
    """Fetch full detail for a single Upwork job posting."""
    client = get_jobs_client()
    record = client.get_job(job_id)
    render_record(record, table=table, properties=properties)
