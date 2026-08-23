"""Main entry point for MyChart CLI."""

from __future__ import annotations

from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .auth_flow import mychart_login
from .client import get_client
from .config import get_config

FHIR_TYPE_COLUMNS = ["type", "interaction", "search_params"]
RESOURCE_COLUMNS = ["resourceType", "id", "status"]

app = create_app(name="mychart", help="Epic MyChart SMART on FHIR patient record CLI", version=__version__)
metadata_app = typer.Typer(help="Inspect the FHIR server metadata", no_args_is_help=True)
oauth_app = typer.Typer(help="Inspect SMART OAuth discovery", no_args_is_help=True)
types_app = typer.Typer(help="Inspect supported FHIR resource types", no_args_is_help=True)
resources_app = typer.Typer(help="Read FHIR resources", no_args_is_help=True)
patient_app = typer.Typer(help="Read the patient context", no_args_is_help=True)
summary_app = typer.Typer(help="Read grouped clinical summaries", no_args_is_help=True)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _select_object_properties(row: dict, properties: Optional[str]) -> dict:
    fields = _property_fields(properties)
    if not fields:
        return row
    filtered = apply_properties_filter([row], properties)
    return filtered[0] if filtered else {}


def _render_rows(
    rows: List[dict],
    table: bool,
    properties: Optional[str],
    empty: str,
    default_columns: List[str],
) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or [column for column in default_columns if column in rows[0]]
    if not columns:
        columns = list(rows[0].keys())[:6]
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _render_object(row: dict, table: bool, properties: Optional[str]) -> None:
    row = _select_object_properties(row, properties)
    if not table:
        print_json(row)
        return
    print_table(
        [{"field": key, "value": str(value)} for key, value in row.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


@metadata_app.command("get")
@command
def get_metadata(
    metadata_id: Optional[str] = typer.Argument(None, help="Metadata record ID from metadata list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get the FHIR CapabilityStatement."""
    if metadata_id not in {None, "capability-statement"}:
        print_error("Unknown metadata ID. Use 'capability-statement'.")
        raise typer.Exit(1)
    _render_object(get_client(require_auth=False).get_metadata(), table, properties)


@metadata_app.command("list")
@command
def list_metadata(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of metadata records"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List metadata records."""
    _validate(filter)
    metadata = get_client(require_auth=False).get_metadata()
    rows = [
        {
            "id": "capability-statement",
            "resourceType": metadata.get("resourceType"),
            "fhirVersion": metadata.get("fhirVersion"),
            "status": metadata.get("status"),
        }
    ][:limit]
    if filter:
        rows = apply_filters(rows, filter)
    _render_rows(rows, table, properties, "No metadata records found.", ["id", "resourceType", "fhirVersion", "status"])


@oauth_app.command("get")
@command
def get_oauth_endpoints(
    endpoint_id: Optional[str] = typer.Argument(None, help="OAuth endpoint ID from oauth list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get SMART OAuth endpoints advertised by the server."""
    endpoints = get_client(require_auth=False).get_oauth_endpoints()
    if endpoint_id is None:
        _render_object(endpoints, table, properties)
        return
    if endpoint_id not in endpoints:
        print_error(f"Unknown OAuth endpoint ID: {endpoint_id}")
        raise typer.Exit(1)
    _render_object({"id": endpoint_id, "url": endpoints[endpoint_id]}, table, properties)


@oauth_app.command("list")
@command
def list_oauth_endpoints(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of OAuth endpoints"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List SMART OAuth endpoints advertised by the server."""
    _validate(filter)
    endpoints = get_client(require_auth=False).get_oauth_endpoints()
    rows = [{"id": name, "url": url} for name, url in sorted(endpoints.items())][:limit]
    if filter:
        rows = apply_filters(rows, filter)
    _render_rows(rows, table, properties, "No OAuth endpoints found.", ["id", "url"])


@types_app.command("list")
@command
def list_resource_types(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of resource types"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List FHIR resource types advertised by the server."""
    _validate(filter)
    rows = get_client(require_auth=False).list_resource_types(limit=limit)
    if filter:
        rows = apply_filters(rows, filter)
    _render_rows(rows, table, properties, "No FHIR resource types found.", FHIR_TYPE_COLUMNS)


@types_app.command("get")
@command
def get_resource_type(
    resource_type: str = typer.Argument(..., help="FHIR resource type, such as Observation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get CapabilityStatement details for one FHIR resource type."""
    _render_object(get_client(require_auth=False).get_resource_type(resource_type), table, properties)


@resources_app.command("list")
@command
def list_resources(
    resource_type: str = typer.Argument(..., help="FHIR resource type, such as Observation"),
    patient_id: Optional[str] = typer.Option(None, "--patient-id", help="Patient ID; defaults to the saved token patient"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of resources"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="FHIR search filter (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List FHIR resources with server-side search parameters."""
    _validate(filter)
    rows = get_client().list_resource(
        resource_type,
        patient_id=patient_id,
        limit=limit,
        filters=filter,
    )
    _render_rows(rows, table, properties, "No FHIR resources found.", RESOURCE_COLUMNS)


@resources_app.command("get")
@command
def get_resource(
    resource_type: str = typer.Argument(..., help="FHIR resource type, such as Observation"),
    resource_id: str = typer.Argument(..., help="FHIR resource ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one FHIR resource by type and ID."""
    _render_object(get_client().get_resource(resource_type, resource_id), table, properties)


@resources_app.command("search")
@command
def search_resources(
    resource_type: str = typer.Argument(..., help="FHIR resource type, such as Observation"),
    query: str = typer.Argument(..., help="FHIR _text search query"),
    patient_id: Optional[str] = typer.Option(None, "--patient-id", help="Patient ID; defaults to the saved token patient"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of resources"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Additional FHIR search filter"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search FHIR resources using the standard _text search parameter."""
    filters = list(filter or [])
    filters.append(f"_text:eq:{query}")
    rows = get_client().list_resource(
        resource_type,
        patient_id=patient_id,
        limit=limit,
        filters=filters,
    )
    _render_rows(rows, table, properties, "No FHIR resources found.", RESOURCE_COLUMNS)


@patient_app.command("get")
@command
def get_patient(
    patient_id: Optional[str] = typer.Argument(None, help="Patient ID; defaults to the saved token patient"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get the current or requested Patient resource."""
    config = get_config()
    if not config.has_credentials() and patient_id:
        _render_object(get_client(require_auth=False).get_sandbox_test_patient(patient_id), table, properties)
        return
    _render_object(get_client().get_patient(patient_id), table, properties)


@patient_app.command("list")
@command
def list_patients(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of patients"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="FHIR Patient search filter (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List Patient resources."""
    _validate(filter)
    config = get_config()
    if config.has_credentials():
        rows = get_client().list_resource("Patient", limit=limit, filters=filter)
    else:
        rows = get_client(require_auth=False).list_sandbox_test_patients(limit=limit)
        if filter:
            rows = apply_filters(rows, filter)
    _render_rows(rows, table, properties, "No Patient resources found.", ["resourceType", "id", "gender", "birthDate"])


@summary_app.command("get")
@command
def get_summary(
    patient_id: Optional[str] = typer.Option(None, "--patient-id", help="Patient ID; defaults to the saved token patient"),
    resource: Optional[List[str]] = typer.Option(
        None,
        "--resource",
        "-r",
        help="FHIR resource type to include; repeat for multiple types",
    ),
    limit_per_resource: int = typer.Option(10, "--limit-per-resource", "-l", help="Maximum resources per type"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a grouped read-only clinical summary."""
    row = get_client().get_summary(
        patient_id=patient_id,
        resource_types=resource,
        limit_per_resource=limit_per_resource,
    )
    _render_object(row, table, properties)


app.add_typer(create_auth_app(get_config, tool_name="mychart", login_handler=mychart_login), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
app.add_typer(metadata_app, name="metadata")
app.add_typer(oauth_app, name="oauth")
app.add_typer(types_app, name="types")
app.add_typer(resources_app, name="resources")
app.add_typer(patient_app, name="patient")
app.add_typer(summary_app, name="summary")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
