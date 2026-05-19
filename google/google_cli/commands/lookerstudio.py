"""Looker Studio commands."""
COMMAND_CREDENTIALS = {
    "reports": ["no_auth"],
}

import json
from typing import Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client
from ..lookerstudio_client import (
    LookerStudioClient,
    build_report_link,
    parse_bool,
    parse_linking_parameter,
)
from ..models.lookerstudio import (
    LookerStudioDataSourceParameter,
    LookerStudioRole,
)

app = typer.Typer(help="Manage Looker Studio assets", no_args_is_help=True)
reports_app = typer.Typer(help="Manage Looker Studio reports", no_args_is_help=True)
app.add_typer(reports_app, name="reports")


def get_lookerstudio_client(profile: Optional[str] = None) -> LookerStudioClient:
    """Create a Looker Studio client for the selected Google profile."""
    return LookerStudioClient.from_google_client(get_client(profile=profile), profile=profile)


def _parse_properties(properties: Optional[str]) -> Optional[list[str]]:
    if properties is None:
        return None
    parsed = [property_name.strip() for property_name in properties.split(",")]
    if any(property_name == "" for property_name in parsed):
        raise ValueError("Expected comma-separated property names")
    return parsed


def _model_to_dict(item) -> dict:
    return item.model_dump(mode="json")


def _select_properties(item: dict, properties: Optional[list[str]]) -> dict:
    if properties is None:
        return item
    return {property_name: item.get(property_name) for property_name in properties}


def _select_collection_properties(items: list[dict], properties: Optional[list[str]]) -> list[dict]:
    if properties is None:
        return items
    return [_select_properties(item, properties) for item in items]


def _build_data_source_parameters(
    *,
    data_source: Optional[list[str]],
    ga_alias: Optional[str],
    ga_account_id: Optional[str],
    ga_property_id: Optional[str],
    ga_view_id: Optional[str],
    ga_refresh_fields: Optional[str],
) -> list[LookerStudioDataSourceParameter]:
    parameters = [parse_linking_parameter(value) for value in data_source or []]
    ga_fields = [ga_account_id, ga_property_id, ga_view_id, ga_refresh_fields]
    if any(field is not None for field in ga_fields):
        if ga_alias is None:
            raise ValueError("Expected --ga-alias when setting Google Analytics data source fields")
        if ga_account_id is None:
            raise ValueError("Expected --ga-account-id when setting Google Analytics data source fields")
        if ga_property_id is None:
            raise ValueError("Expected --ga-property-id when setting Google Analytics data source fields")
        parameters.append(
            LookerStudioDataSourceParameter(
                alias=ga_alias,
                key="connector",
                value="googleAnalytics",
            )
        )
        parameters.append(
            LookerStudioDataSourceParameter(
                alias=ga_alias,
                key="accountId",
                value=ga_account_id,
            )
        )
        parameters.append(
            LookerStudioDataSourceParameter(
                alias=ga_alias,
                key="propertyId",
                value=ga_property_id,
            )
        )
        if ga_view_id is not None:
            parameters.append(
                LookerStudioDataSourceParameter(
                    alias=ga_alias,
                    key="viewId",
                    value=ga_view_id,
                )
            )
        if ga_refresh_fields is not None:
            parameters.append(
                LookerStudioDataSourceParameter(
                    alias=ga_alias,
                    key="refreshFields",
                    value=parse_bool(ga_refresh_fields),
                )
            )
    return parameters


@reports_app.command("list")
def reports_list(
    limit: int = typer.Option(1000, "--limit", "-l", help="Maximum number of reports to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated properties to include in output",
    ),
    title: Optional[str] = typer.Option(None, "--title", help="Search title string"),
    owner: Optional[str] = typer.Option(None, "--owner", help="Asset owner's email"),
    include_trashed: bool = typer.Option(
        False,
        "--include-trashed",
        help="Include reports from trash",
    ),
    order_by: Optional[str] = typer.Option(None, "--order-by", help="Sort field"),
    page_token: Optional[str] = typer.Option(None, "--page-token", help="Page token"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Looker Studio report assets."""
    try:
        selected_properties = _parse_properties(properties)
        client = get_lookerstudio_client(profile=profile)
        reports = client.search_reports(
            title=title,
            owner=owner,
            include_trashed=include_trashed,
            order_by=order_by,
            page_size=limit,
            page_token=page_token,
        )
        output = [_model_to_dict(report) for report in reports]
        if filter:
            output = apply_filters(output, filter)
        output = _select_collection_properties(output, selected_properties)
        if table:
            columns = selected_properties or ["name", "title", "owner", "create_time"]
            print_table(output, columns, columns)
        else:
            print_json(output)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@reports_app.command("get")
def reports_get(
    report_id: str = typer.Argument(..., help="Report ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated properties to include in output",
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a Looker Studio report asset."""
    try:
        selected_properties = _parse_properties(properties)
        client = get_lookerstudio_client(profile=profile)
        output = _select_properties(_model_to_dict(client.get_report(report_id)), selected_properties)
        if table:
            columns = selected_properties or ["name", "title", "owner", "create_time"]
            print_table([output], columns, columns)
        else:
            print_json(output)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@reports_app.command("create-link")
def reports_create_link(
    report_id: str = typer.Option(..., "--report-id", help="Template report ID"),
    report_name: Optional[str] = typer.Option(None, "--report-name", help="Created report name"),
    page_id: Optional[str] = typer.Option(None, "--page-id", help="Initial page ID"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Initial mode: view or edit"),
    explain: bool = typer.Option(False, "--explain", help="Show Linking API debug info"),
    measurement_id: Optional[str] = typer.Option(
        None,
        "--measurement-id",
        help="Google Analytics measurement ID for report usage",
    ),
    keep_measurement_id: bool = typer.Option(
        False,
        "--keep-measurement-id",
        help="Use the template report measurement ID",
    ),
    data_source: Optional[list[str]] = typer.Option(
        None,
        "--data-source",
        help="Data source parameter as alias.key=value",
    ),
    ga_alias: Optional[str] = typer.Option(None, "--ga-alias", help="Google Analytics data source alias"),
    ga_account_id: Optional[str] = typer.Option(None, "--ga-account-id", help="Google Analytics account ID"),
    ga_property_id: Optional[str] = typer.Option(None, "--ga-property-id", help="Google Analytics property ID"),
    ga_view_id: Optional[str] = typer.Option(None, "--ga-view-id", help="Universal Analytics view ID"),
    ga_refresh_fields: Optional[str] = typer.Option(
        None,
        "--ga-refresh-fields",
        help="Whether to refresh fields: true or false",
    ),
    embed: bool = typer.Option(False, "--embed", help="Generate an embed create URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a Looker Studio Linking API URL for a report."""
    try:
        link = build_report_link(
            report_id=report_id,
            report_name=report_name,
            page_id=page_id,
            mode=mode,
            explain=explain,
            measurement_id=measurement_id,
            keep_measurement_id=keep_measurement_id if keep_measurement_id else None,
            data_source_parameters=_build_data_source_parameters(
                data_source=data_source,
                ga_alias=ga_alias,
                ga_account_id=ga_account_id,
                ga_property_id=ga_property_id,
                ga_view_id=ga_view_id,
                ga_refresh_fields=ga_refresh_fields,
            ),
            embed=embed,
        )
        if table:
            print_table([link], ["report_id", "url"], ["report_id", "url"])
        else:
            print_json(link)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@reports_app.command("update-link")
def reports_update_link(
    report_id: str = typer.Argument(..., help="Report ID"),
    report_name: Optional[str] = typer.Option(None, "--report-name", help="Created report name"),
    page_id: Optional[str] = typer.Option(None, "--page-id", help="Initial page ID"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Initial mode: view or edit"),
    explain: bool = typer.Option(False, "--explain", help="Show Linking API debug info"),
    measurement_id: Optional[str] = typer.Option(
        None,
        "--measurement-id",
        help="Google Analytics measurement ID for report usage",
    ),
    keep_measurement_id: bool = typer.Option(
        False,
        "--keep-measurement-id",
        help="Use the template report measurement ID",
    ),
    data_source: Optional[list[str]] = typer.Option(
        None,
        "--data-source",
        help="Data source parameter as alias.key=value",
    ),
    ga_alias: Optional[str] = typer.Option(None, "--ga-alias", help="Google Analytics data source alias"),
    ga_account_id: Optional[str] = typer.Option(None, "--ga-account-id", help="Google Analytics account ID"),
    ga_property_id: Optional[str] = typer.Option(None, "--ga-property-id", help="Google Analytics property ID"),
    ga_view_id: Optional[str] = typer.Option(None, "--ga-view-id", help="Universal Analytics view ID"),
    ga_refresh_fields: Optional[str] = typer.Option(
        None,
        "--ga-refresh-fields",
        help="Whether to refresh fields: true or false",
    ),
    embed: bool = typer.Option(False, "--embed", help="Generate an embed create URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a Linking API URL with data-source params."""
    try:
        link = build_report_link(
            report_id=report_id,
            report_name=report_name,
            page_id=page_id,
            mode=mode,
            explain=explain,
            measurement_id=measurement_id,
            keep_measurement_id=keep_measurement_id if keep_measurement_id else None,
            data_source_parameters=_build_data_source_parameters(
                data_source=data_source,
                ga_alias=ga_alias,
                ga_account_id=ga_account_id,
                ga_property_id=ga_property_id,
                ga_view_id=ga_view_id,
                ga_refresh_fields=ga_refresh_fields,
            ),
            embed=embed,
        )
        if table:
            print_table([link], ["report_id", "url"], ["report_id", "url"])
        else:
            print_json(link)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@reports_app.command("permissions-get")
def permissions_get(
    report_id: str = typer.Argument(..., help="Report ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get permissions for a Looker Studio report."""
    try:
        result = get_lookerstudio_client(profile=profile).get_permissions(report_id)
        if table:
            print_table([result], ["etag"], ["etag"])
        else:
            print_json(result)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@reports_app.command("permissions-add-members")
def permissions_add_members(
    report_id: str = typer.Argument(..., help="Report ID"),
    role: LookerStudioRole = typer.Option(..., "--role", help="Role to add members to"),
    members: list[str] = typer.Option(..., "--member", help="Member to add"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Add members to a Looker Studio report permission role."""
    try:
        result = get_lookerstudio_client(profile=profile).add_members(report_id, role, members)
        if table:
            print_table([result], ["etag"], ["etag"])
        else:
            print_json(result)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@reports_app.command("permissions-patch")
def permissions_patch(
    report_id: str = typer.Argument(..., help="Report ID"),
    permissions_json: str = typer.Option(
        ...,
        "--permissions-json",
        help="Permissions map JSON",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Patch permissions for a Looker Studio report."""
    try:
        permissions = json.loads(permissions_json)
        if not isinstance(permissions, dict):
            raise ValueError("Expected --permissions-json to contain a JSON object")
        result = get_lookerstudio_client(profile=profile).patch_permissions(report_id, permissions)
        if table:
            print_table([result], ["etag"], ["etag"])
        else:
            print_json(result)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@reports_app.command("permissions-revoke-all")
def permissions_revoke_all(
    report_id: str = typer.Argument(..., help="Report ID"),
    members: list[str] = typer.Option(..., "--member", help="Member to remove"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Revoke all permissions for members on a Looker Studio report."""
    try:
        result = get_lookerstudio_client(profile=profile).revoke_all_permissions(report_id, members)
        if table:
            print_table([result], ["etag"], ["etag"])
        else:
            print_json(result)
    except Exception as error:
        raise typer.Exit(handle_error(error))
