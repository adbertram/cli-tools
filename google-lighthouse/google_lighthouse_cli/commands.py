"""Audit commands for the Google Lighthouse wrapper."""

from __future__ import annotations

COMMAND_CREDENTIALS = {
    "run": ["custom"],
    "list": ["custom"],
    "get": ["custom"],
}

from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.filters import FilterValidationError
from cli_tools_shared.output import handle_error, print_error, print_json, print_table

from .client import get_client

app = typer.Typer(help="Manage Lighthouse audits", no_args_is_help=True)

DEFAULT_COLUMNS = [
    "id",
    "url",
    "form_factor",
    "scores.performance",
    "scores.accessibility",
    "scores.best_practices",
    "scores.seo",
]
DEFAULT_HEADERS = ["ID", "URL", "Form Factor", "Performance", "Accessibility", "Best Practices", "SEO"]


def model_to_dict(item):
    """Convert a Pydantic model or dict to a dict for output shaping."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json", by_alias=True)
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    value = data
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        if part not in value:
            return None
        value = value[part]
    return value


def extract_fields(records: list, fields: list[str]) -> list[dict]:
    """Extract selected fields from records, preserving requested field names."""
    results = []
    for record in records:
        selected = {}
        for field in fields:
            selected[field] = extract_field(record, field)
        results.append(selected)
    return results


def parse_properties(properties: Optional[str]) -> Optional[list[str]]:
    """Parse a comma-separated --properties value."""
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",")]
    for field in fields:
        if field == "":
            raise typer.BadParameter("properties cannot contain empty field names")
    return fields


def validate_form_factor(form_factor: str) -> None:
    """Validate the Lighthouse form factor."""
    if form_factor not in {"desktop", "mobile"}:
        print_error("form-factor must be 'desktop' or 'mobile'")
        raise typer.Exit(1)


def print_records(records, table: bool, properties: Optional[str], single: bool = False) -> None:
    """Print records as JSON or table."""
    fields = parse_properties(properties)
    if fields is not None:
        output = extract_fields([records] if single else records, fields)
        columns = fields
        headers = fields
    else:
        if single:
            output = model_to_dict(records)
        else:
            output = [model_to_dict(record) for record in records]
        columns = DEFAULT_COLUMNS
        headers = DEFAULT_HEADERS

    if table:
        print_table(output if not single else [output], columns, headers)
        return

    if fields is not None and single:
        print_json(output[0])
        return

    print_json(output)


@app.command("run")
def audits_run(
    url: str = typer.Argument(..., help="URL to audit"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    form_factor: str = typer.Option("desktop", "--form-factor", help="Lighthouse form factor: desktop or mobile"),
    chrome_flags: str = typer.Option("--headless=new", "--chrome-flags", help="Chrome flags passed to Lighthouse"),
    timeout: int = typer.Option(180, "--timeout", help="Maximum audit runtime in seconds"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """Run a Lighthouse audit and save JSON/HTML artifacts."""
    try:
        validate_form_factor(form_factor)
        summary = get_client().run_audit(
            url=url,
            form_factor=form_factor,
            chrome_flags=chrome_flags,
            timeout_seconds=timeout,
        )
        print_records(summary, table=table, properties=properties, single=True)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@app.command("list")
def audits_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of audits to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """List saved Lighthouse audits."""
    try:
        audits = get_client().list_audits(limit=limit, filters=filter)
        print_records(audits, table=table, properties=properties)
    except FilterValidationError as error:
        print_error(str(error))
        raise typer.Exit(1)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@app.command("get")
def audits_get(
    audit_id: str = typer.Argument(..., help="Audit ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """Get a saved Lighthouse audit summary."""
    try:
        audit = get_client().get_audit(audit_id)
        print_records(audit, table=table, properties=properties, single=True)
    except Exception as error:
        raise typer.Exit(handle_error(error))
