"""Main entry point for Weather CLI."""

from enum import Enum
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import get_client
from .config import get_config


COLUMNS = ["zip_code", "place_name", "state", "temperature_display", "humidity_display", "observed_at"]
FORECAST_COLUMNS = ["zip_code", "place_name", "state", "start_date", "end_date", "days_count"]


class TemperatureUnit(str, Enum):
    fahrenheit = "fahrenheit"
    celsius = "celsius"


app = create_app(name="weather", help="CLI interface for Weather API", version=__version__)
conditions_app = typer.Typer(help="Get weather conditions by ZIP code", no_args_is_help=True)
forecast_app = typer.Typer(help="Get weather forecasts by ZIP code", no_args_is_help=True)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _select_properties(row: dict, properties: Optional[str]) -> dict:
    fields = _property_fields(properties)
    if not fields:
        return row
    filtered = apply_properties_filter([row], properties)
    return filtered[0] if filtered else {}


def _resolve_zip_code(zip_code: Optional[str]) -> str:
    if zip_code:
        return zip_code
    default_zip = get_config().default_zip
    if default_zip:
        return default_zip
    print_error("ZIP code is required. Pass ZIP_CODE or set DEFAULT_ZIP in ~/.local/share/cli-tools/weather/.env.")
    raise typer.Exit(1)


def _resolve_zip_codes(zip_codes: Optional[List[str]]) -> List[str]:
    if zip_codes:
        return zip_codes
    return [_resolve_zip_code(None)]


def _render(
    row: dict,
    table: bool,
    properties: Optional[str],
    columns: List[str] = COLUMNS,
    empty_message: str = "No conditions found.",
) -> None:
    selected = _select_properties(row, properties)
    if not table:
        print_json(selected)
        return
    if not selected:
        print_info(empty_message)
        return
    columns = _property_fields(properties) or columns
    print_table([selected], columns, [column.replace("_", " ").title() for column in columns], max_columns=0)


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render_list(
    rows: List[dict],
    table: bool,
    properties: Optional[str],
    columns: List[str] = COLUMNS,
    empty_message: str = "No conditions found.",
) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty_message)
        return
    columns = fields or columns
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns], max_columns=0)


@conditions_app.command("list")
@command
def list_conditions(
    zip_codes: Optional[List[str]] = typer.Argument(None, help="US ZIP codes"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of ZIP codes to process"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    unit: TemperatureUnit = typer.Option(
        TemperatureUnit.fahrenheit,
        "--unit",
        "-u",
        help="Temperature unit",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List current temperature and humidity for one or more ZIP codes."""
    _validate(filter)
    try:
        rows = get_client().list_conditions(zip_codes=_resolve_zip_codes(zip_codes), limit=limit, unit=unit.value)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    if filter:
        rows = apply_filters(rows, filter)
    _render_list(rows, table, properties)


@conditions_app.command("get")
@command
def get_conditions(
    zip_code: Optional[str] = typer.Argument(None, help="US ZIP code"),
    unit: TemperatureUnit = typer.Option(
        TemperatureUnit.fahrenheit,
        "--unit",
        "-u",
        help="Temperature unit",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get current temperature and humidity for a ZIP code."""
    try:
        row = get_client().get_conditions(zip_code=_resolve_zip_code(zip_code), unit=unit.value)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    _render(row, table, properties)


@forecast_app.command("list")
@command
def list_forecasts(
    zip_codes: Optional[List[str]] = typer.Argument(None, help="US ZIP codes"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of ZIP codes to process"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    days: int = typer.Option(7, "--days", "-d", help="Forecast days, 1-16"),
    unit: TemperatureUnit = typer.Option(
        TemperatureUnit.fahrenheit,
        "--unit",
        "-u",
        help="Temperature unit",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List daily forecasts for one or more ZIP codes."""
    _validate(filter)
    try:
        rows = get_client().list_forecasts(
            zip_codes=_resolve_zip_codes(zip_codes),
            limit=limit,
            days=days,
            unit=unit.value,
        )
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    if filter:
        rows = apply_filters(rows, filter)
    _render_list(rows, table, properties, FORECAST_COLUMNS, "No forecasts found.")


@forecast_app.command("get")
@command
def get_forecast(
    zip_code: Optional[str] = typer.Argument(None, help="US ZIP code"),
    days: int = typer.Option(7, "--days", "-d", help="Forecast days, 1-16"),
    unit: TemperatureUnit = typer.Option(
        TemperatureUnit.fahrenheit,
        "--unit",
        "-u",
        help="Temperature unit",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a daily forecast for a ZIP code."""
    try:
        row = get_client().get_forecast(zip_code=_resolve_zip_code(zip_code), days=days, unit=unit.value)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    _render(row, table, properties, FORECAST_COLUMNS, "No forecast found.")


app.add_typer(conditions_app, name="conditions")
app.add_typer(forecast_app, name="forecast")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
