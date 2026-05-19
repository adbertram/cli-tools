"""Demo environments command module."""
import typer
from typing import Optional, List

from ..client import get_client, ClientError
from ..output import print_error, print_json, print_table
from ..filter_map import translate_filters
from ..filters import apply_limit, apply_properties_filter

app = typer.Typer(help="Manage demo environment records")


@app.command("list")
def list_environments(
    provider: Optional[str] = typer.Option(None, "--provider", help="Filter by provider name"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., provider:eq:Azure)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of records to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List demo environment records.

    Examples:
        coursecraft environments list
        coursecraft environments list --provider Azure
        coursecraft environments list --properties "id,fields.Name,fields.Environment ID"
    """
    try:
        client = get_client()

        filter_list = list(filter) if filter else []
        if provider:
            filter_list.append(f"provider:eq:{provider}")

        formula = translate_filters(filter_list, "Demo Environments") if filter_list else None
        records = client.list_records("Demo Environments", formula)
        records = apply_limit(records, limit)

        if properties and not table_output:
            records = apply_properties_filter(records, properties)

        if table_output:
            rows = []
            for record in records:
                fields = record.get("fields", {})
                rows.append({
                    "id": record["id"],
                    "environment_id": fields.get("Environment ID", ""),
                    "name": fields.get("Name", ""),
                    "provider": fields.get("Provider", ""),
                    "status": fields.get("Status", ""),
                })
            print_table(
                rows,
                ["id", "environment_id", "name", "provider", "status"],
                ["Record ID", "Environment ID", "Name", "Provider", "Status"],
            )
        else:
            print_json(records)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def get_environment(
    environment: str = typer.Argument(..., help="Environment record ID, Environment ID, or exact Name"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to include (supports dot notation)"),
    table_output: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a single demo environment record.

    Examples:
        coursecraft environments get azure-adam-the-automator
        coursecraft environments get azure-adam-the-automator --properties "id,fields.Name,fields.Notes"
    """
    try:
        client = get_client()
        record_id = client.resolve_environment_id(environment)
        record = client.get_record("Demo Environments", record_id)

        if not record:
            print_error(f"Demo environment not found: {environment}")
            raise typer.Exit(1)

        if properties and not table_output:
            record = apply_properties_filter([record], properties)[0]

        if table_output:
            fields = record.get("fields", {})
            rows = [{
                "id": record["id"],
                "environment_id": fields.get("Environment ID", ""),
                "name": fields.get("Name", ""),
                "provider": fields.get("Provider", ""),
                "status": fields.get("Status", ""),
                "tenant": fields.get("Tenant Name", ""),
                "subscription": fields.get("Subscription Name", ""),
            }]
            print_table(
                rows,
                ["id", "environment_id", "name", "provider", "status", "tenant", "subscription"],
                ["Record ID", "Environment ID", "Name", "Provider", "Status", "Tenant", "Subscription"],
            )
        else:
            print_json(record)

    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
}
