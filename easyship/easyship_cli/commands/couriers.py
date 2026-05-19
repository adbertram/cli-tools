"""Courier commands for Easyship CLI."""
from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.output import handle_error, print_json, print_info, print_table

from ..client import get_client

COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"],
    "get": ["personal_access_token"],
}

app = typer.Typer(help="List and inspect active Easyship couriers", no_args_is_help=True)


def _model_to_dict(item):
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def _extract_field(item, field: str):
    value = _model_to_dict(item)
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _extract_fields(items: list, fields: list[str]) -> list[dict]:
    extracted = []
    for item in items:
        row = {}
        for field in fields:
            row[field] = _extract_field(item, field)
        extracted.append(row)
    return extracted


@app.command("list")
def couriers_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of couriers to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:eq:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List active couriers from `GET /couriers`."""
    try:
        client = get_client()
        couriers = client.list_couriers(limit=limit, filters=filter)
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            couriers = _extract_fields(couriers, fields)

        if table:
            if couriers:
                fields = [field.strip() for field in properties.split(",")] if properties else [
                    "id",
                    "umbrella_name",
                    "country_alpha2",
                    "auth_state",
                    "state",
                ]
                print_table(couriers, fields, [field.replace("_", " ").title() for field in fields])
            else:
                print_info("No couriers found.")
        else:
            print_json(couriers)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def couriers_get(
    courier_id: str = typer.Argument(..., help="Easyship courier ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get courier details from `GET /couriers/{courier_id}`."""
    try:
        client = get_client()
        courier = client.get_courier(courier_id)
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            courier = _extract_fields([courier], fields)[0]

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table([courier], fields, [field.replace("_", " ").title() for field in fields])
            else:
                print_table(
                    [{"field": key, "value": value} for key, value in _model_to_dict(courier).items() if value is not None],
                    ["field", "value"],
                    ["Field", "Value"],
                )
        else:
            print_json(courier)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
